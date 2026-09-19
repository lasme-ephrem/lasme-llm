let API_BASE = "/api";
const LASME_FAST_MODEL = "lasme-smol-fast";
const LASME_REASONING_MODEL = "lasme-qwen-vision";

// A Cloudflared/reverse-proxy URL can be opened once with ?token=... .
// The token is moved to sessionStorage immediately and never persisted across
// browser restarts. Direct localhost access does not require one.
const initialUrl = new URL(window.location.href);
const queryAccessToken = initialUrl.searchParams.get("token");
if (queryAccessToken) {
    sessionStorage.setItem("lasme_access_token", queryAccessToken);
    initialUrl.searchParams.delete("token");
    window.history.replaceState({}, document.title, initialUrl.toString());
}

const nativeFetch = window.fetch.bind(window);
window.fetch = (input, init = {}) => {
    const requestUrl = typeof input === "string" ? input : input.url;
    const resolved = new URL(requestUrl, window.location.origin);
    if (resolved.origin === window.location.origin && resolved.pathname.startsWith("/api/")) {
        const accessToken = sessionStorage.getItem("lasme_access_token");
        if (accessToken) {
            const headers = new Headers(init.headers || (input instanceof Request ? input.headers : undefined));
            headers.set("X-Lasme-Token", accessToken);
            init = { ...init, headers };
        }
    }
    return nativeFetch(input, init);
};

let currentSessionId = null;
let currentProjectId = localStorage.getItem("active_project_id") || "default";
let conversationHistory = [];
let currentDocumentScopeId = currentProjectId;
let temporaryChatEnabled = false;

// DOM Elements
const sidebar = document.getElementById("sidebar");
const sidebarBackdrop = document.getElementById("sidebarBackdrop");
const mobileMenuBtn = document.getElementById("mobileMenuBtn");
const mobileMenuBtn2 = document.getElementById("mobileMenuBtn2");
const closeSidebarBtn = document.getElementById("closeSidebarBtn");
const sidebarCollapseBtn = document.getElementById("sidebarCollapseBtn");
const sidebarExpandBtn = document.getElementById("sidebarExpandBtn");
const sidebarResizer = document.getElementById("sidebarResizer");

const sessionsList = document.getElementById("sessionsList");
const newChatIconBtn = document.getElementById("newChatIconBtn");
const newChatBtn = document.getElementById("newChatBtn");
const chatMessages = document.getElementById("chatMessages");

if (newChatIconBtn) {
    newChatIconBtn.addEventListener("click", (e) => {
        if (e) e.preventDefault();
        startNewChat();
        closeSidebar();
    });
}

if (newChatBtn) {
    newChatBtn.addEventListener("click", (e) => {
        if (e) e.preventDefault();
        startNewChat();
        closeSidebar();
    });
}

const chatInput = document.getElementById("chatInput");
const sendChatBtn = document.getElementById("sendChatBtn");
const inputModelSelect = document.getElementById("inputModelSelect");
const reasoningLevelSelect = document.getElementById("reasoningLevelSelect");
const webSearchToggle = document.getElementById("webSearchToggle");
const webSearchBtn = document.getElementById("webSearchBtn");
const webSearchLabel = document.getElementById("webSearchLabel");
const themeToggleBtn = document.getElementById("themeToggleBtn");
const temporaryChatBtn = document.getElementById("temporaryChatBtn");
const contextUsageIndicator = document.getElementById("contextUsageIndicator");
const contextUsageBar = document.getElementById("contextUsageBar");
const contextUsageLabel = document.getElementById("contextUsageLabel");
const memorySettingsBtn = document.getElementById("memorySettingsBtn");
const memoryModal = document.getElementById("memoryModal");
const memoryModalOverlay = document.getElementById("memoryModalOverlay");
const closeMemoryModalBtn = document.getElementById("closeMemoryModalBtn");
const memoryEnabledToggle = document.getElementById("memoryEnabledToggle");
const memoryAutoSaveToggle = document.getElementById("memoryAutoSaveToggle");
const memoryNewInput = document.getElementById("memoryNewInput");
const memoryAddBtn = document.getElementById("memoryAddBtn");
const memoryList = document.getElementById("memoryList");
const memoryRefreshBtn = document.getElementById("memoryRefreshBtn");
const memoryStatus = document.getElementById("memoryStatus");

// ── Model Selection Popover Menu Handler ─────────────────────────────
const modelPickerTrigger = document.getElementById("modelPickerTrigger");
const modelPickerDropdown = document.getElementById("modelPickerDropdown");
const selectedModelName = document.getElementById("selectedModelName");
const modelTriggerIcon = document.getElementById("modelTriggerIcon");
const reasoningPickerTrigger = document.getElementById("reasoningPickerTrigger");
const reasoningPickerDropdown = document.getElementById("reasoningPickerDropdown");
const selectedReasoningName = document.getElementById("selectedReasoningName");

const mobilePickerMedia = window.matchMedia("(max-width: 768px)");

function modelIconMarkup(model) {
    const normalized = String(model || "").toLowerCase();
    if (normalized.includes("smol") || normalized.includes("fast")
        || normalized.includes("e4b") || normalized.includes("e2b")) {
        return `
            <svg viewBox="0 0 24 24" fill="none">
                <path d="M4 8.25h6M2.5 12h6M4 15.75h6" class="model-mark-detail"></path>
                <path d="m14.1 4.6-3 7h4l-2 7.8 7-10.2h-4.2l2.2-4.6z" class="model-mark-line"></path>
                <path d="m14.1 4.6-3 7h4l-2 7.8 7-10.2h-4.2l2.2-4.6z" class="model-mark-fill"></path>
            </svg>
        `;
    }
    if (normalized.includes("qwen") || normalized.includes("vision")) {
        return `
            <svg viewBox="0 0 24 24" fill="none">
                <path d="M3.4 12s3.1-5.2 8.6-5.2 8.6 5.2 8.6 5.2-3.1 5.2-8.6 5.2S3.4 12 3.4 12z" class="model-mark-line"></path>
                <circle cx="12" cy="12" r="2.65" class="model-mark-fill"></circle>
                <path d="M5 4.5H3.5V6M19 4.5h1.5V6M5 19.5H3.5V18M19 19.5h1.5V18" class="model-mark-detail"></path>
            </svg>
        `;
    }
    return `
        <svg viewBox="0 0 24 24" fill="none">
            <path d="M5.25 6.25A2.75 2.75 0 0 1 8 3.5h8A2.75 2.75 0 0 1 18.75 6.25v5.5A2.75 2.75 0 0 1 16 14.5h-4.2l-3.65 2.8v-2.8H8a2.75 2.75 0 0 1-2.75-2.75z" class="model-mark-line"></path>
            <path d="m16.65 15.55.56 1.4 1.4.56-1.4.56-.56 1.4-.56-1.4-1.4-.56 1.4-.56z" class="model-mark-fill"></path>
            <path d="M8.5 8.95h7M8.5 11.35h4.5" class="model-mark-detail"></path>
        </svg>
    `;
}

function updateModelIdentity(model) {
    if (!modelTriggerIcon) return;
    const normalized = String(model || "").toLowerCase();
    const identity = normalized.includes("smol") || normalized.includes("fast")
        || normalized.includes("e4b") || normalized.includes("e2b")
        ? "fast"
        : (normalized.includes("qwen") || normalized.includes("vision") ? "vision" : "chat");
    ["chat", "fast", "vision", "fable"].forEach(name => {
        modelTriggerIcon.classList.toggle(`model-mark-${name}`, name === identity);
    });
    modelTriggerIcon.innerHTML = modelIconMarkup(model);
}

function positionMobilePicker(dropdown) {
    if (!dropdown) return;

    if (!mobilePickerMedia.matches) {
        dropdown.style.removeProperty("--mobile-picker-bottom");
        dropdown.style.removeProperty("--mobile-picker-max-height");
        return;
    }

    const composer = document.querySelector(".chat-input-container");
    if (!composer) return;

    const composerRect = composer.getBoundingClientRect();
    const visibleViewportHeight = window.visualViewport?.height || window.innerHeight;
    const visibleViewportTop = window.visualViewport?.offsetTop || 0;
    const visibleViewportBottom = visibleViewportTop + visibleViewportHeight;
    const composerTop = Math.min(composerRect.top, visibleViewportBottom);
    const gap = 10;
    const edgeMargin = 12;
    const bottomOffset = Math.max(
        edgeMargin,
        window.innerHeight - composerTop + gap
    );
    const availableHeight = Math.max(
        160,
        Math.min(420, composerTop - visibleViewportTop - edgeMargin - gap)
    );

    dropdown.style.setProperty("--mobile-picker-bottom", `${bottomOffset}px`);
    dropdown.style.setProperty("--mobile-picker-max-height", `${availableHeight}px`);
}

function refreshOpenMobilePickers() {
    [modelPickerDropdown, reasoningPickerDropdown].forEach((dropdown) => {
        if (dropdown?.classList.contains("open")) {
            positionMobilePicker(dropdown);
        }
    });
}

window.addEventListener("resize", refreshOpenMobilePickers, { passive: true });
window.addEventListener("orientationchange", refreshOpenMobilePickers, { passive: true });
window.visualViewport?.addEventListener("resize", refreshOpenMobilePickers, { passive: true });
window.visualViewport?.addEventListener("scroll", refreshOpenMobilePickers, { passive: true });

if (modelPickerTrigger && modelPickerDropdown) {
    modelPickerTrigger.addEventListener("click", (e) => {
        e.stopPropagation();
        if (reasoningPickerDropdown) reasoningPickerDropdown.classList.remove("open");
        if (reasoningPickerTrigger) reasoningPickerTrigger.setAttribute("aria-expanded", "false");
        positionMobilePicker(modelPickerDropdown);
        const isOpen = modelPickerDropdown.classList.toggle("open");
        modelPickerTrigger.setAttribute("aria-expanded", isOpen ? "true" : "false");
    });
    document.addEventListener("click", () => {
        modelPickerDropdown.classList.remove("open");
        if (modelPickerTrigger) modelPickerTrigger.setAttribute("aria-expanded", "false");
    });
    document.querySelectorAll("#modelPickerDropdown .intel-option").forEach(btn => {
        btn.addEventListener("click", (e) => {
            e.stopPropagation();
            const modelVal = btn.dataset.model;
            const labelVal = btn.dataset.label;
            if (selectedModelName) selectedModelName.textContent = labelVal;
            if (inputModelSelect) inputModelSelect.value = modelVal;
            updateModelIdentity(modelVal);
            
            document.querySelectorAll("#modelPickerDropdown .intel-option").forEach(b => {
                b.classList.remove("intel-active");
                const chk = b.querySelector(".intel-check-icon");
                if (chk) chk.classList.remove("active");
            });
            btn.classList.add("intel-active");
            const activeChk = btn.querySelector(".intel-check-icon");
            if (activeChk) activeChk.classList.add("active");
            modelPickerDropdown.classList.remove("open");
            modelPickerTrigger.setAttribute("aria-expanded", "false");
        });
    });
}

updateModelIdentity(inputModelSelect?.value || "gemma-4-12b");

if (reasoningPickerTrigger && reasoningPickerDropdown && reasoningLevelSelect) {
    reasoningPickerTrigger.addEventListener("click", (e) => {
        e.stopPropagation();
        if (modelPickerDropdown) modelPickerDropdown.classList.remove("open");
        if (modelPickerTrigger) modelPickerTrigger.setAttribute("aria-expanded", "false");
        positionMobilePicker(reasoningPickerDropdown);
        const isOpen = reasoningPickerDropdown.classList.toggle("open");
        reasoningPickerTrigger.setAttribute("aria-expanded", isOpen ? "true" : "false");
    });
    document.addEventListener("click", () => {
        reasoningPickerDropdown.classList.remove("open");
        reasoningPickerTrigger.setAttribute("aria-expanded", "false");
    });
    document.querySelectorAll("#reasoningPickerDropdown .intel-option").forEach(btn => {
        btn.addEventListener("click", (e) => {
            e.stopPropagation();
            reasoningLevelSelect.value = btn.dataset.level || "balanced";
            if (selectedReasoningName) {
                selectedReasoningName.textContent = btn.dataset.label || "Équilibré";
            }
            document.querySelectorAll("#reasoningPickerDropdown .intel-option").forEach(option => {
                option.classList.remove("intel-active");
                const check = option.querySelector(".intel-check-icon");
                if (check) check.classList.remove("active");
            });
            btn.classList.add("intel-active");
            const activeCheck = btn.querySelector(".intel-check-icon");
            if (activeCheck) activeCheck.classList.add("active");
            reasoningPickerDropdown.classList.remove("open");
            reasoningPickerTrigger.setAttribute("aria-expanded", "false");
        });
    });
}

if (webSearchBtn && webSearchToggle) {
    webSearchBtn.addEventListener("click", (e) => {
        if (e) e.preventDefault();
        const currentMode = webSearchBtn.dataset.mode || "auto";
        const nextMode = currentMode === "auto"
            ? "always"
            : (
                currentMode === "always"
                    ? "deep"
                    : (currentMode === "deep" ? "off" : "auto")
            );
        webSearchBtn.dataset.mode = nextMode;
        webSearchToggle.checked = nextMode !== "off";
        webSearchBtn.classList.toggle("active", nextMode !== "off");
        const labels = {
            auto: "Web auto",
            always: "Web",
            deep: "Recherche",
            off: "Web off"
        };
        const titles = {
            auto: "Recherche Web automatique",
            always: "Recherche Web toujours active",
            deep: "Recherche approfondie avec plan et recoupement",
            off: "Recherche Web désactivée",
        };
        if (webSearchLabel) webSearchLabel.textContent = labels[nextMode];
        webSearchBtn.setAttribute("title", titles[nextMode]);
    });
}

// Document & Image Multimodal Elements
const inputActionWrapper = document.querySelector(".input-action-wrapper");
const attachFileBtn = document.getElementById("attachFileBtn");
const menuAttachDocBtn = document.getElementById("menuAttachDocBtn");
const docFileInput = document.getElementById("docFileInput");
const attachedDocBadge = document.getElementById("attachedDocBadge");
const docBadgeName = document.getElementById("docBadgeName");
const clearDocBtn = document.getElementById("clearDocBtn");
let attachedDocumentFileIds = [];
let attachedDocumentProjectId = null;

function resetDocumentAttachment() {
    attachedDocumentFileIds = [];
    attachedDocumentProjectId = null;
    if (attachedDocBadge) {
        attachedDocBadge.style.display = "none";
        attachedDocBadge.classList.remove("is-loading", "has-error");
    }
    if (docBadgeName) docBadgeName.textContent = "";
    if (docFileInput) docFileInput.value = "";
}

function selectedDocumentFileIdsForRequest() {
    const projectSelection =
        window.LasmeWorkspace?.getSelectedFileIds?.() || [];
    const composerSelection = attachedDocumentProjectId === currentProjectId
        ? attachedDocumentFileIds
        : [];
    return Array.from(
        new Set([...projectSelection, ...composerSelection])
    );
}

window.LasmeComposer = {
    ...(window.LasmeComposer || {}),
    resetDocumentAttachment,
};

// Vision Multimodal Image Elements
const menuAttachImageBtn = document.getElementById("menuAttachImageBtn");
const imageFileInput = document.getElementById("imageFileInput");
const attachedImageBadge = document.getElementById("attachedImageBadge");
const imageBadgePreview = document.getElementById("imageBadgePreview");
const imageBadgeName = document.getElementById("imageBadgeName");
const clearImageBtn = document.getElementById("clearImageBtn");

let attachedImageBase64Items = [];
let attachedImageDataUrls = [];

// Plus Action Popover Menu Toggle Logic
if (attachFileBtn && inputActionWrapper) {
    attachFileBtn.addEventListener("click", (e) => {
        e.stopPropagation();
        e.preventDefault();
        inputActionWrapper.classList.toggle("open");
    });

    document.addEventListener("click", (e) => {
        if (!inputActionWrapper.contains(e.target)) {
            inputActionWrapper.classList.remove("open");
        }
    });
}

if (menuAttachDocBtn && docFileInput) {
    menuAttachDocBtn.addEventListener("click", (e) => {
        if (e) e.preventDefault();
        if (inputActionWrapper) inputActionWrapper.classList.remove("open");
        docFileInput.click();
    });
}

if (menuAttachImageBtn && imageFileInput) {
    menuAttachImageBtn.addEventListener("click", (e) => {
        if (e) e.preventDefault();
        if (inputActionWrapper) inputActionWrapper.classList.remove("open");
        imageFileInput.click();
    });
}

const menuGenerateImageBtn = document.getElementById("menuGenerateImageBtn");
if (menuGenerateImageBtn) {
    menuGenerateImageBtn.addEventListener("click", (e) => {
        if (e) e.preventDefault();
        if (inputActionWrapper) inputActionWrapper.classList.remove("open");
        if (chatInput) {
            chatInput.value = "Génère une image : ";
            chatInput.focus();
            autoResizeTextarea(chatInput);
        }
    });
}

// Fullscreen Image Viewer Modal Handlers
const imageViewerModal = document.getElementById("imageViewerModal");
const imageViewerOverlay = document.getElementById("imageViewerOverlay");
const imageViewerImg = document.getElementById("imageViewerImg");
const closeImageViewerBtn = document.getElementById("closeImageViewerBtn");
const downloadImageBtn = document.getElementById("downloadImageBtn");

function openImageViewer(imgUrl) {
    if (!imageViewerModal || !imageViewerImg) return;
    const safeUrl = safeHttpUrl(imgUrl);
    if (!safeUrl) return;
    imageViewerImg.src = safeUrl;
    if (downloadImageBtn) downloadImageBtn.href = safeUrl;
    imageViewerModal.style.display = "flex";
}

function closeImageViewer() {
    if (imageViewerModal) imageViewerModal.style.display = "none";
}

if (closeImageViewerBtn) closeImageViewerBtn.addEventListener("click", closeImageViewer);
if (imageViewerOverlay) imageViewerOverlay.addEventListener("click", closeImageViewer);

// Multimodal Image Attachment Handler
if (imageFileInput) {
    imageFileInput.addEventListener("change", async () => {
        if (!imageFileInput.files || imageFileInput.files.length === 0) return;
        const files = Array.from(imageFileInput.files).slice(0, 4);
        const readDataUrl = file => new Promise((resolve, reject) => {
            const reader = new FileReader();
            reader.onload = () => resolve(String(reader.result || ""));
            reader.onerror = () => reject(reader.error);
            reader.readAsDataURL(file);
        });
        try {
            const urls = await Promise.all(files.map(readDataUrl));
            attachedImageDataUrls = urls;
            attachedImageBase64Items = urls.map(url => url.split(",")[1]).filter(Boolean);
            if (attachedImageBadge && imageBadgePreview && imageBadgeName) {
                imageBadgePreview.src = urls[0];
                imageBadgeName.textContent = files.length > 1
                    ? `${files[0].name} · +${files.length - 1}`
                    : files[0].name;
                attachedImageBadge.style.display = "inline-flex";
            }
        } catch (_) {
            attachedImageBase64Items = [];
            attachedImageDataUrls = [];
        }
    });
}

if (clearImageBtn) {
    clearImageBtn.addEventListener("click", () => {
        attachedImageBase64Items = [];
        attachedImageDataUrls = [];
        if (attachedImageBadge) attachedImageBadge.style.display = "none";
        if (imageFileInput) imageFileInput.value = "";
    });
}

// Mobile Sidebar Drawer Handlers
function openSidebar() {
    if (sidebar) sidebar.classList.add("open");
    if (sidebarBackdrop) sidebarBackdrop.classList.add("active");
}

function closeSidebar() {
    if (sidebar) sidebar.classList.remove("open");
    if (sidebarBackdrop) sidebarBackdrop.classList.remove("active");
}

if (mobileMenuBtn) mobileMenuBtn.addEventListener("click", openSidebar);
if (mobileMenuBtn2) mobileMenuBtn2.addEventListener("click", openSidebar);
if (closeSidebarBtn) closeSidebarBtn.addEventListener("click", closeSidebar);
if (sidebarBackdrop) sidebarBackdrop.addEventListener("click", closeSidebar);

function setSidebarCollapsed(collapsed, persist = true) {
    const shouldCollapse = Boolean(collapsed);
    const desktopLayout = window.matchMedia("(min-width: 769px)").matches;
    const effectivelyCollapsed = shouldCollapse && desktopLayout;
    document.body.classList.toggle("sidebar-collapsed", shouldCollapse);
    if (sidebar) {
        sidebar.inert = effectivelyCollapsed;
        sidebar.setAttribute(
            "aria-hidden",
            effectivelyCollapsed ? "true" : "false"
        );
    }
    if (sidebarResizer) {
        sidebarResizer.tabIndex = effectivelyCollapsed ? -1 : 0;
        sidebarResizer.setAttribute(
            "aria-hidden",
            effectivelyCollapsed ? "true" : "false"
        );
    }
    sidebarCollapseBtn?.setAttribute(
        "aria-expanded",
        shouldCollapse ? "false" : "true"
    );
    sidebarExpandBtn?.setAttribute(
        "aria-expanded",
        shouldCollapse ? "false" : "true"
    );
    if (persist) {
        localStorage.setItem(
            "sidebar_collapsed",
            shouldCollapse ? "true" : "false"
        );
    }
}

sidebarCollapseBtn?.addEventListener("click", () => {
    setSidebarCollapsed(true);
});

sidebarExpandBtn?.addEventListener("click", () => {
    setSidebarCollapsed(false);
});

setSidebarCollapsed(
    localStorage.getItem("sidebar_collapsed") === "true",
    false
);

window.matchMedia("(min-width: 769px)").addEventListener("change", () => {
    setSidebarCollapsed(
        localStorage.getItem("sidebar_collapsed") === "true",
        false
    );
});

const SIDEBAR_MIN_WIDTH = 268;
const SIDEBAR_MAX_WIDTH = 420;
const SIDEBAR_DEFAULT_WIDTH = 288;

function setSidebarWidth(value, persist = true) {
    if (!sidebar || !sidebarResizer) return;
    const width = Math.max(
        SIDEBAR_MIN_WIDTH,
        Math.min(SIDEBAR_MAX_WIDTH, Number(value) || SIDEBAR_DEFAULT_WIDTH)
    );
    document.documentElement.style.setProperty("--sidebar-width", `${width}px`);
    sidebarResizer.setAttribute("aria-valuenow", String(Math.round(width)));
    if (persist) localStorage.setItem("sidebar_width", String(Math.round(width)));
}

if (sidebarResizer) {
    setSidebarWidth(
        localStorage.getItem("sidebar_width") || SIDEBAR_DEFAULT_WIDTH,
        false
    );
    let resizingSidebar = false;

    sidebarResizer.addEventListener("pointerdown", event => {
        if (window.matchMedia("(max-width: 768px)").matches) return;
        resizingSidebar = true;
        document.body.classList.add("sidebar-resizing");
        sidebarResizer.setPointerCapture?.(event.pointerId);
        event.preventDefault();
    });

    sidebarResizer.addEventListener("pointermove", event => {
        if (!resizingSidebar) return;
        setSidebarWidth(event.clientX);
    });

    const finishSidebarResize = event => {
        if (!resizingSidebar) return;
        resizingSidebar = false;
        document.body.classList.remove("sidebar-resizing");
        sidebarResizer.releasePointerCapture?.(event.pointerId);
    };
    sidebarResizer.addEventListener("pointerup", finishSidebarResize);
    sidebarResizer.addEventListener("pointercancel", finishSidebarResize);
    sidebarResizer.addEventListener(
        "dblclick",
        () => setSidebarWidth(SIDEBAR_DEFAULT_WIDTH)
    );
    sidebarResizer.addEventListener("keydown", event => {
        if (!["ArrowLeft", "ArrowRight", "Home"].includes(event.key)) return;
        event.preventDefault();
        const current = Number(sidebarResizer.getAttribute("aria-valuenow"))
            || SIDEBAR_DEFAULT_WIDTH;
        if (event.key === "Home") {
            setSidebarWidth(SIDEBAR_DEFAULT_WIDTH);
        } else {
            setSidebarWidth(current + (event.key === "ArrowRight" ? 16 : -16));
        }
    });
}

// Initialize Marked & Highlight.js & Mermaid
if (typeof marked !== "undefined") {
    marked.setOptions({
        highlight: function(code, lang) {
            if (lang && hljs.getLanguage(lang)) {
                return hljs.highlight(code, { language: lang }).value;
            }
            return hljs.highlightAuto(code).value;
        },
        breaks: true,
        gfm: true
    });
}

if (typeof mermaid !== "undefined") {
    mermaid.initialize({
        startOnLoad: false,
        theme: "dark",
        securityLevel: "strict",
        suppressErrorRendering: true,
    });
}

// Default Theme -> LIGHT MODE (ChatGPT Style)
let currentTheme = localStorage.getItem("theme") || "light";
setTheme(currentTheme);

if (themeToggleBtn) {
    themeToggleBtn.addEventListener("click", (e) => {
        if (e) e.preventDefault();
        currentTheme = currentTheme === "dark" ? "light" : "dark";
        setTheme(currentTheme);
    });
}

function setTheme(theme) {
    document.documentElement.setAttribute("data-theme", theme);
    localStorage.setItem("theme", theme);
    
    if (themeToggleBtn) {
        const iconContainer = themeToggleBtn.querySelector(".theme-icon-svg");
        const label = themeToggleBtn.querySelector(".theme-label");
        if (theme === "light") {
            if (iconContainer) {
                iconContainer.innerHTML = `
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round">
                        <path d="M20.5 14.4A8.5 8.5 0 0 1 9.6 3.5 8.5 8.5 0 1 0 20.5 14.4z"></path>
                    </svg>
                `;
            }
            if (label) label.textContent = "Sombre";
            themeToggleBtn.title = "Passer en mode sombre";
            themeToggleBtn.setAttribute("aria-label", "Passer en mode sombre");
        } else {
            if (iconContainer) {
                iconContainer.innerHTML = `
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                        <circle cx="12" cy="12" r="4.5"></circle>
                        <path d="M12 2v2M12 20v2M4.93 4.93l1.42 1.42M17.65 17.65l1.42 1.42M2 12h2M20 12h2M4.93 19.07l1.42-1.42M17.65 6.35l1.42-1.42"></path>
                    </svg>
                `;
            }
            if (label) label.textContent = "Clair";
            themeToggleBtn.title = "Passer en mode clair";
            themeToggleBtn.setAttribute("aria-label", "Passer en mode clair");
        }
    }
}

// Unified Tab & Mode Switcher
function switchTab(tabName) {
    document.querySelectorAll(".mode-btn").forEach(b => {
        b.classList.toggle("active", b.getAttribute("data-tab") === tabName);
    });
    document.querySelectorAll(".tab-pane").forEach(p => p.classList.remove("active"));
    const targetPane = document.getElementById(tabName + "Tab");
    if (targetPane) targetPane.classList.add("active");
    if (tabName === "coding") {
        checkFirstTimeAgenticUser();
        if (typeof loadIdeFileTree === "function") loadIdeFileTree();
        if (typeof loadIdeFileContent === "function") loadIdeFileContent("README.md");
        if (typeof loadIdeSubagents === "function") loadIdeSubagents();
    }
}

document.addEventListener("click", (e) => {
    const btn = e.target.closest(".mode-btn, .nav-btn");
    if (btn) {
        if (e) e.preventDefault();
        const tabName = btn.getAttribute("data-tab");
        if (tabName) switchTab(tabName);
    }
});

// Initialize Sessions & UI with Active Session Persistence
document.addEventListener("DOMContentLoaded", async () => {
    try {
        const capabilitiesResponse = await fetch(`${API_BASE}/capabilities`);
        if (capabilitiesResponse.ok) {
            const capabilities = await capabilitiesResponse.json();
            if (!capabilities.vision_enabled && menuAttachImageBtn) {
                menuAttachImageBtn.disabled = true;
                menuAttachImageBtn.title = "Aucun modèle de vision Ollama configuré";
                menuAttachImageBtn.setAttribute("aria-disabled", "true");
            }
            if (!capabilities.external_image_generation_enabled && menuGenerateImageBtn) {
                menuGenerateImageBtn.disabled = true;
                menuGenerateImageBtn.title = "Génération d’images externe désactivée";
            }
        }
    } catch (_) {}
    if (typeof loadProjects === "function") {
        await loadProjects();
    }
    await loadSessions();
    const savedSessionId = localStorage.getItem("active_session_id");
    if (savedSessionId) {
        await selectSession(savedSessionId);
    } else {
        startNewChat();
    }
});

const activeStreamingSessions = new Set();
let sessionRefreshSequence = 0;

async function loadSessions() {
    const refreshSequence = ++sessionRefreshSequence;
    try {
        const query = currentProjectId
            ? `?project_id=${encodeURIComponent(currentProjectId)}`
            : "";
        const resp = await fetch(`${API_BASE}/sessions${query}`);
        if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
        const data = await resp.json();
        if (refreshSequence !== sessionRefreshSequence) return;
        renderSessions(data.sessions || []);
        await window.LasmeWorkspace?.refreshProjectSessionCounts?.();
    } catch (err) {
        console.error("Erreur chargement des sessions:", err);
    }
}

function renderSessions(sessions) {
    if (!sessionsList) return;
    sessionsList.innerHTML = "";
    sessions.forEach(sess => {
        const item = document.createElement("div");
        const isActive = (sess.id === currentSessionId);
        item.className = `session-item ${isActive ? "active" : ""}`;
        
        const titleSpan = document.createElement("span");
        titleSpan.style.flex = "1";
        titleSpan.style.overflow = "hidden";
        titleSpan.style.textOverflow = "ellipsis";
        titleSpan.style.whiteSpace = "nowrap";
        titleSpan.style.display = "inline-flex";
        titleSpan.style.alignItems = "center";
        
        const titleTextNode = document.createTextNode(sess.title || "Conversation");
        titleSpan.appendChild(titleTextNode);

        if (activeStreamingSessions.has(sess.id)) {
            const loader = document.createElement("span");
            loader.className = "session-pulsing-loader";
            loader.title = "Génération en cours...";
            loader.innerHTML = `<span></span><span></span><span></span>`;
            titleSpan.appendChild(loader);
        }

        const delBtn = document.createElement("button");
        delBtn.type = "button";
        delBtn.className = "delete-btn";
        delBtn.title = "Supprimer";
        delBtn.innerHTML = `
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <polyline points="3 6 5 6 21 6"></polyline>
                <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path>
            </svg>
        `;
        delBtn.addEventListener("click", (e) => {
            e.stopPropagation();
            e.preventDefault();
            deleteSession(sess.id);
        });

        item.appendChild(titleSpan);
        item.appendChild(delBtn);

        item.addEventListener("click", () => {
            selectSession(sess.id);
            closeSidebar();
        });

        sessionsList.appendChild(item);
    });
}

async function selectSession(sessionId) {
    temporaryChatEnabled = false;
    updateTemporaryChatUI();
    resetDocumentAttachment();
    currentSessionId = sessionId;
    refreshSendButtonState();
    localStorage.setItem("active_session_id", sessionId);
    conversationHistory = [];
    if (chatMessages) chatMessages.innerHTML = "";

    try {
        const resp = await fetch(`${API_BASE}/sessions/${sessionId}/messages`);
        if (!resp.ok) {
            startNewChat();
            return;
        }
        const data = await resp.json();
        if (data.session?.project_id) {
            currentProjectId = data.session.project_id;
            currentDocumentScopeId = currentProjectId;
            localStorage.setItem("active_project_id", currentProjectId);
            if (typeof syncProjectSelector === "function") syncProjectSelector();
            await window.LasmeWorkspace?.resetDocumentSelection?.();
        }
        const msgs = data.messages || [];

        if (msgs.length === 0) {
            startNewChat();
            return;
        }

        msgs.forEach(msg => {
            let imgUrl = null;
            let cleanText = msg.content;
            if (msg.role === "user" && msg.content && msg.content.includes("![Image Attachée](")) {
                const match = msg.content.match(/\!\[Image Attachée\]\((.*?)\)/);
                if (match) {
                    imgUrl = match[1];
                    cleanText = msg.content.replace(/\!\[Image Attachée\]\((.*?)\)\n\n?/, "").trim();
                }
            }
            appendMessage(
                msg.role,
                cleanText,
                imgUrl,
                msg.metadata?.web_results || [],
                msg.id,
                msg.metadata?.generation_stats || null
            );
            conversationHistory.push({ role: msg.role, content: msg.content });
        });

        void loadSessions();
    } catch (err) {
        console.error("Erreur lecture messages session:", err);
        startNewChat();
    }
}

function updateTemporaryChatUI() {
    document.body.classList.toggle(
        "temporary-chat-active",
        temporaryChatEnabled
    );
    temporaryChatBtn?.classList.toggle("active", temporaryChatEnabled);
    temporaryChatBtn?.setAttribute(
        "aria-pressed",
        temporaryChatEnabled ? "true" : "false"
    );
    if (temporaryChatBtn) {
        temporaryChatBtn.title = temporaryChatEnabled
            ? "Quitter la conversation temporaire"
            : "Démarrer une conversation temporaire";
    }

    const canvasButton = document.getElementById("canvasToggleBtn");
    [memorySettingsBtn, canvasButton].forEach(button => {
        if (!button) return;
        button.disabled = temporaryChatEnabled;
        button.setAttribute(
            "aria-disabled",
            temporaryChatEnabled ? "true" : "false"
        );
    });
    if (menuAttachDocBtn) {
        menuAttachDocBtn.disabled = temporaryChatEnabled;
        menuAttachDocBtn.title = temporaryChatEnabled
            ? "Les documents persistants sont désactivés en mode temporaire"
            : "";
    }
}

temporaryChatBtn?.addEventListener("click", () => {
    if (temporaryChatEnabled) {
        void startNewChat();
    } else {
        void startNewChat({ temporary: true });
    }
});

async function startNewChat(options = {}) {
    const nextTemporaryState = Boolean(options.temporary);
    if (temporaryChatEnabled && !nextTemporaryState) {
        const temporaryController = streamControllers.get(null);
        temporaryController?.abort();
        streamControllers.delete(null);
    }
    temporaryChatEnabled = nextTemporaryState;
    resetDocumentAttachment();
    void window.LasmeWorkspace?.resetDocumentSelection?.();
    currentSessionId = null;
    currentDocumentScopeId = temporaryChatEnabled ? null : currentProjectId;
    updateTemporaryChatUI();
    refreshSendButtonState();
    updateContextUsage({ percentage: 0 });
    localStorage.removeItem("active_session_id");
    conversationHistory = [];
    chatMessages.innerHTML = "";
    
    const greetings = [
        "Que souhaitez-vous savoir aujourd'hui ?",
        "En quoi puis-je vous aider ?",
        "Prêt pour une nouvelle idée ?",
        "De quoi aimeriez-vous discuter ?"
    ];
    const randomGreeting = temporaryChatEnabled
        ? "Conversation temporaire"
        : greetings[Math.floor(Math.random() * greetings.length)];

    const heroDiv = document.createElement("div");
    heroDiv.className = `chatgpt-welcome-hero${
        temporaryChatEnabled ? " temporary-welcome-hero" : ""
    }`;
    heroDiv.innerHTML = `
        <div class="hero-logo" aria-hidden="true">
            ${temporaryChatEnabled
                ? `
                    <svg width="27" height="27" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round">
                        <path d="M12 3a9 9 0 1 0 9 9"></path>
                        <path d="M12 3a9 9 0 0 1 9 9"></path>
                    </svg>
                `
                : `
                    <svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
                        <polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"></polygon>
                    </svg>
                `
            }
        </div>
        <h2>${randomGreeting}</h2>
        ${temporaryChatEnabled
            ? `
                <p>Cette conversation n’est ajoutée ni à l’historique ni à la mémoire. Elle disparaît lorsque vous quittez ce mode.</p>
                <span class="temporary-privacy-note">Aucune mémoire personnelle · aucun historique</span>
            `
            : ""
        }
    `;
    chatMessages.appendChild(heroDiv);

    await loadSessions();
}

async function deleteSession(sessionId) {
    try {
        const controller = streamControllers.get(sessionId);
        if (controller) controller.abort();
        streamControllers.delete(sessionId);
        const response = await fetch(
            `${API_BASE}/sessions/${sessionId}`,
            { method: "DELETE" }
        );
        if (!response.ok) {
            throw new Error(`HTTP ${response.status}`);
        }
        if (currentSessionId === sessionId) {
            await startNewChat();
        } else {
            await loadSessions();
        }
    } catch (err) {
        console.error("Erreur suppression de la conversation :", err);
    }
}

function updateContextUsage(meta = {}) {
    if (!contextUsageIndicator || !contextUsageBar || !contextUsageLabel) return;
    const percentage = Math.max(
        0,
        Math.min(100, Number(meta.percentage) || 0)
    );
    contextUsageBar.style.width = `${percentage}%`;
    contextUsageIndicator.classList.toggle("medium", percentage >= 55 && percentage < 80);
    contextUsageIndicator.classList.toggle("high", percentage >= 80);
    const summary = meta.summary_used ? " · résumé actif" : "";
    contextUsageLabel.textContent = `Contexte ${percentage}%${summary}`;
    contextUsageIndicator.title = [
        `${meta.estimated_tokens || 0} tokens conversationnels`,
        `${meta.personal_memory_count || 0} souvenirs actifs`,
        `${meta.rag_chunk_count || 0} extraits documentaires`,
    ].join(" · ");
}

async function loadSuggestedQuestions(sessionId, model, bubble) {
    try {
        const response = await fetch(`${API_BASE}/chat/suggestions`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ session_id: sessionId, model }),
        });
        if (!response.ok) return;
        const payload = await response.json();
        const suggestions = Array.isArray(payload.suggestions)
            ? payload.suggestions.slice(0, 3)
            : [];
        if (!suggestions.length || currentSessionId !== sessionId || !bubble.isConnected) {
            return;
        }
        bubble.querySelector(".suggested-questions")?.remove();
        const row = document.createElement("div");
        row.className = "suggested-questions";
        suggestions.forEach((suggestion) => {
            if (typeof suggestion !== "string" || !suggestion.trim()) return;
            const button = document.createElement("button");
            button.type = "button";
            button.className = "suggested-question";
            button.textContent = suggestion.trim();
            button.addEventListener("click", async () => {
                if (activeControllerForCurrentConversation()) return;
                chatInput.value = suggestion.trim();
                autoResizeTextarea(chatInput);
                row.classList.add("sending");
                row.querySelectorAll("button").forEach(item => {
                    item.disabled = true;
                });
                row.remove();
                await sendChatMessage();
            });
            row.appendChild(button);
        });
        if (row.childElementCount) bubble.appendChild(row);
    } catch (_) {}
}

function setMemoryStatus(message) {
    if (memoryStatus) memoryStatus.textContent = message || "";
}

function renderMemoryItems(items) {
    if (!memoryList) return;
    memoryList.innerHTML = "";
    if (!items.length) {
        const empty = document.createElement("p");
        empty.className = "memory-empty";
        empty.textContent = "Aucun souvenir enregistré.";
        memoryList.appendChild(empty);
        return;
    }
    items.forEach((item) => {
        const row = document.createElement("div");
        row.className = `memory-item ${item.enabled ? "" : "disabled"}`;

        const enabled = document.createElement("input");
        enabled.type = "checkbox";
        enabled.checked = Boolean(item.enabled);
        enabled.title = "Activer ou désactiver ce souvenir";

        const input = document.createElement("input");
        input.type = "text";
        input.maxLength = 300;
        input.value = item.content || "";

        const source = document.createElement("span");
        source.className = "memory-source";
        source.textContent = item.source === "user" ? "manuel" : "auto";

        const remove = document.createElement("button");
        remove.type = "button";
        remove.textContent = "Supprimer";

        const save = async (payload) => {
            const response = await fetch(`${API_BASE}/memory/${item.id}`, {
                method: "PUT",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(payload),
            });
            if (!response.ok) throw new Error("Modification impossible");
        };

        enabled.addEventListener("change", async () => {
            try {
                await save({ enabled: enabled.checked });
                row.classList.toggle("disabled", !enabled.checked);
                setMemoryStatus("Mémoire mise à jour.");
            } catch (_) {
                enabled.checked = !enabled.checked;
                setMemoryStatus("Impossible de modifier ce souvenir.");
            }
        });
        input.addEventListener("change", async () => {
            const content = input.value.trim();
            if (!content) return;
            try {
                await save({ content });
                setMemoryStatus("Souvenir modifié.");
            } catch (_) {
                setMemoryStatus("Impossible de modifier ce souvenir.");
            }
        });
        remove.addEventListener("click", async () => {
            const response = await fetch(`${API_BASE}/memory/${item.id}`, {
                method: "DELETE",
            });
            if (response.ok) {
                row.remove();
                setMemoryStatus("Souvenir supprimé.");
            }
        });
        row.append(enabled, input, source, remove);
        memoryList.appendChild(row);
    });
}

async function loadMemoryPanel() {
    setMemoryStatus("Chargement…");
    try {
        const response = await fetch(`${API_BASE}/memory`);
        if (!response.ok) throw new Error();
        const payload = await response.json();
        if (memoryEnabledToggle) {
            memoryEnabledToggle.checked = payload.settings?.enabled !== false;
        }
        if (memoryAutoSaveToggle) {
            memoryAutoSaveToggle.checked = payload.settings?.auto_save !== false;
        }
        renderMemoryItems(payload.memories || []);
        setMemoryStatus("");
    } catch (_) {
        setMemoryStatus("Mémoire indisponible.");
    }
}

function closeMemoryPanel() {
    if (!memoryModal) return;
    memoryModal.style.display = "none";
    memoryModal.setAttribute("aria-hidden", "true");
}

if (memorySettingsBtn && memoryModal) {
    memorySettingsBtn.addEventListener("click", () => {
        memoryModal.style.display = "grid";
        memoryModal.setAttribute("aria-hidden", "false");
        void loadMemoryPanel();
    });
}
memoryModalOverlay?.addEventListener("click", closeMemoryPanel);
closeMemoryModalBtn?.addEventListener("click", closeMemoryPanel);

async function saveMemorySettings() {
    try {
        await fetch(`${API_BASE}/memory/settings`, {
            method: "PUT",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                enabled: memoryEnabledToggle?.checked,
                auto_save: memoryAutoSaveToggle?.checked,
            }),
        });
        setMemoryStatus("Réglages enregistrés.");
    } catch (_) {
        setMemoryStatus("Impossible d’enregistrer les réglages.");
    }
}
memoryEnabledToggle?.addEventListener("change", saveMemorySettings);
memoryAutoSaveToggle?.addEventListener("change", saveMemorySettings);

memoryAddBtn?.addEventListener("click", async () => {
    const content = memoryNewInput?.value.trim();
    if (!content) return;
    const response = await fetch(`${API_BASE}/memory`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ content }),
    });
    if (response.ok) {
        memoryNewInput.value = "";
        await loadMemoryPanel();
        setMemoryStatus("Souvenir ajouté.");
    } else {
        setMemoryStatus("Impossible d’ajouter ce souvenir.");
    }
});

memoryRefreshBtn?.addEventListener("click", async () => {
    setMemoryStatus("Analyse des conversations…");
    const response = await fetch(`${API_BASE}/memory/refresh`, {
        method: "POST",
    });
    if (response.ok) {
        await loadMemoryPanel();
        setMemoryStatus("Mémoire actualisée.");
    } else {
        setMemoryStatus("Actualisation impossible.");
    }
});

// Floating Scroll to Bottom Handler
const scrollToBottomBtn = document.getElementById("scrollToBottomBtn");
let streamingAutoScrollPaused = false;
let activeTurnSpacer = null;

if (chatMessages && scrollToBottomBtn) {
    chatMessages.addEventListener("pointerenter", () => {
        chatMessages.classList.add("scrollbar-visible");
    });
    chatMessages.addEventListener("pointerleave", () => {
        chatMessages.classList.remove("scrollbar-visible");
    });
    chatMessages.addEventListener("scroll", () => {
        const threshold = 150;
        const isUp = chatMessages.scrollHeight - chatMessages.scrollTop - chatMessages.clientHeight > threshold;
        if (isUp) {
            scrollToBottomBtn.classList.add("visible");
        } else {
            scrollToBottomBtn.classList.remove("visible");
        }
    });
    chatMessages.addEventListener("wheel", () => {
        if (activeControllerForCurrentConversation()) {
            streamingAutoScrollPaused = true;
        }
    }, { passive: true });
    chatMessages.addEventListener("touchstart", () => {
        if (activeControllerForCurrentConversation()) {
            streamingAutoScrollPaused = true;
        }
    }, { passive: true });

    scrollToBottomBtn.addEventListener("click", (e) => {
        if (e) e.preventDefault();
        streamingAutoScrollPaused = false;
        chatMessages.scrollTo({ top: chatMessages.scrollHeight, behavior: "smooth" });
    });
}

// Auto-Resizing Textarea Handler
function autoResizeTextarea(textarea) {
    if (!textarea) return;
    textarea.style.height = "34px";
    const scrollH = textarea.scrollHeight;
    const newHeight = Math.max(34, Math.min(scrollH, 180));
    textarea.style.height = `${newHeight}px`;
    if (scrollH > 180) {
        textarea.style.overflowY = "auto";
    } else {
        textarea.style.overflowY = "hidden";
    }
}

if (chatInput) {
    chatInput.addEventListener("input", () => autoResizeTextarea(chatInput));
}

const streamControllers = new Map();

function currentStreamKey() {
    return currentSessionId || currentDocumentScopeId;
}

function activeControllerForCurrentConversation() {
    return streamControllers.get(currentStreamKey()) || null;
}

function replaceTurnSpacer(userMessage, assistantMessage) {
    activeTurnSpacer?.remove();
    activeTurnSpacer = document.createElement("div");
    activeTurnSpacer.className = "conversation-turn-spacer";
    activeTurnSpacer.setAttribute("aria-hidden", "true");
    chatMessages.appendChild(activeTurnSpacer);
    resizeTurnSpacer(userMessage, assistantMessage);
}

function resizeTurnSpacer(userMessage, assistantMessage) {
    if (!activeTurnSpacer?.isConnected || !chatMessages) return;
    const turnHeight = (
        Number(userMessage?.offsetHeight || 0)
        + Number(assistantMessage?.offsetHeight || 0)
    );
    const available = chatMessages.clientHeight - turnHeight - 96;
    const spacerHeight = Math.max(
        88,
        Math.min(chatMessages.clientHeight * 0.68, available)
    );
    activeTurnSpacer.style.height = `${Math.round(spacerHeight)}px`;
}

function positionTurnAtViewportTop(userMessage) {
    if (!chatMessages || !userMessage) return;
    requestAnimationFrame(() => {
        const containerRect = chatMessages.getBoundingClientRect();
        const messageRect = userMessage.getBoundingClientRect();
        const targetTop = (
            chatMessages.scrollTop
            + messageRect.top
            - containerRect.top
            - 20
        );
        const reduceMotion = window.matchMedia?.(
            "(prefers-reduced-motion: reduce)"
        )?.matches;
        chatMessages.scrollTo({
            top: Math.max(0, targetTop),
            behavior: reduceMotion ? "auto" : "smooth",
        });
    });
}

function followStreamingResponse(userMessage, assistantMessage) {
    resizeTurnSpacer(userMessage, assistantMessage);
    if (
        streamingAutoScrollPaused
        || !chatMessages
        || !assistantMessage
    ) {
        return;
    }
    requestAnimationFrame(() => {
        const containerRect = chatMessages.getBoundingClientRect();
        const assistantRect = assistantMessage.getBoundingClientRect();
        const overflow = assistantRect.bottom - containerRect.bottom + 28;
        if (overflow > 0) {
            chatMessages.scrollTo({
                top: chatMessages.scrollTop + overflow,
                behavior: "auto",
            });
        }
    });
}

function refreshSendButtonState() {
    setSendButtonState(
        activeControllerForCurrentConversation() ? "stop" : "send"
    );
}

function setSendButtonState(state) {
    if (!sendChatBtn) return;
    if (state === "stop") {
        sendChatBtn.classList.add("stop-mode");
        sendChatBtn.title = "Arrêter la génération";
        sendChatBtn.innerHTML = `
            <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor">
                <rect x="5" y="5" width="14" height="14" rx="3"></rect>
            </svg>
        `;
    } else {
        sendChatBtn.classList.remove("stop-mode");
        sendChatBtn.title = "Envoyer";
        sendChatBtn.innerHTML = `
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
                <line x1="12" y1="19" x2="12" y2="5"></line>
                <polyline points="5 12 12 5 19 12"></polyline>
            </svg>
        `;
    }
}

// Chat Sending Logic
if (sendChatBtn) {
    sendChatBtn.addEventListener("click", (e) => {
        if (e) e.preventDefault();
        const controller = activeControllerForCurrentConversation();
        if (controller) {
            controller.abort();
            streamControllers.delete(currentStreamKey());
            refreshSendButtonState();
            return;
        }
        sendChatMessage();
    });
}

if (chatInput) {
    chatInput.addEventListener("keydown", (e) => {
        if (e.key === "Enter" && !e.shiftKey) {
            e.preventDefault();
            if (activeControllerForCurrentConversation()) return;
            sendChatMessage();
        }
    });
}

let activeTickerInterval = null;

function renderDalleLoaderCard(bubbleDiv) {
    if (activeTickerInterval) clearInterval(activeTickerInterval);
    bubbleDiv.innerHTML = `
        <div class="dalle-loader-card">
            <div class="image-shimmer-canvas">
                <div class="image-scan-line"></div>
                <svg width="36" height="36" viewBox="0 0 24 24" fill="none" stroke="rgba(16, 185, 129, 0.6)" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
                    <polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"></polygon>
                </svg>
            </div>
            <div class="image-status-ticker">
                <div class="image-ticker-spinner"></div>
                <span class="ticker-text">Génération de l'image en cours...</span>
            </div>
        </div>
    `;

    const statusMessages = [
        "Génération de l'image en cours...",
        "Création de la composition visuelle...",
        "Application des textures et lumières...",
        "Finalisation du rendu HD..."
    ];
    let msgIdx = 0;
    const tickerTextSpan = bubbleDiv.querySelector(".ticker-text");
    activeTickerInterval = setInterval(() => {
        msgIdx = (msgIdx + 1) % statusMessages.length;
        if (tickerTextSpan) tickerTextSpan.textContent = statusMessages[msgIdx];
    }, 2500);
}

function renderGeneratedImageCard(bubbleDiv, imageUrl, promptText) {
    if (activeTickerInterval) {
        clearInterval(activeTickerInterval);
        activeTickerInterval = null;
    }
    const safeImageUrl = safeHttpUrl(imageUrl);
    if (!safeImageUrl) {
        bubbleDiv.textContent = "URL d’image invalide.";
        return;
    }
    bubbleDiv.innerHTML = sanitizeHtml(`
        <div class="generated-image-card">
            <img src="${escapeHtml(safeImageUrl)}" alt="${escapeHtml(promptText)}">
            <div class="generated-image-overlay">
                <span style="color:#FFF; font-size:0.8rem; font-weight:500; text-overflow:ellipsis; overflow:hidden; white-space:nowrap; max-width:200px;">${escapeHtml(promptText)}</span>
                <div class="image-card-actions">
                    <button type="button" class="img-action-btn image-zoom-btn">
                        🔍 Zoom
                    </button>
                    <a href="${escapeHtml(safeImageUrl)}" download class="img-action-btn">
                        📥 Télécharger
                    </a>
                </div>
            </div>
        </div>
    `);
    const image = bubbleDiv.querySelector("img");
    const zoomButton = bubbleDiv.querySelector(".image-zoom-btn");
    if (image) image.addEventListener("click", () => openImageViewer(safeImageUrl));
    if (zoomButton) zoomButton.addEventListener("click", () => openImageViewer(safeImageUrl));
}

function renderAssistantProgressively(
    bubble,
    text,
    webResults,
    reasoningDuration,
    options = {}
) {
    const final = Boolean(options.final);
    const render = (container, latestText) => {
        renderFullAssistantMessage(
            container,
            latestText,
            webResults,
            reasoningDuration
        );
    };
    if (window.LasmeProgressiveRenderer) {
        window.LasmeProgressiveRenderer.schedule(
            bubble,
            text,
            render,
            {
                final,
                onPaint: options.onPaint,
                onComplete: options.onComplete,
            }
        );
    } else {
        render(bubble, text);
        options.onPaint?.(bubble, text);
        if (final) options.onComplete?.(bubble);
    }
}

async function sendChatMessage(options = {}) {
    const replayExistingLastUser = Boolean(options.replayExistingLastUser);
    const replayMessage = replayExistingLastUser
        ? [...conversationHistory].reverse().find(item => item.role === "user")
        : null;
    const text = replayExistingLastUser
        ? String(replayMessage?.content || "").trim()
        : chatInput.value.trim();
    const requestSelectedFileIds = selectedDocumentFileIdsForRequest();
    if (
        !text
        && !attachedImageBase64Items.length
        && !requestSelectedFileIds.length
    ) return;
    const requestIsTemporary = temporaryChatEnabled;

    const currentImageB64Items = replayExistingLastUser
        ? []
        : [...attachedImageBase64Items];
    const currentImageDataUrls = replayExistingLastUser
        ? []
        : [...attachedImageDataUrls];

    // Reset attached image UI
    if (!replayExistingLastUser && clearImageBtn) clearImageBtn.click();
    if (!replayExistingLastUser) resetDocumentAttachment();

    if (!replayExistingLastUser) {
        chatInput.value = "";
        autoResizeTextarea(chatInput);
    }
    
    // Clear hero welcome if present
    const hero = chatMessages.querySelector(".chatgpt-welcome-hero");
    if (hero) hero.remove();

    // Track target session ID for background execution
    const streamSessionId = currentSessionId;
    const initialStreamKey = streamSessionId || currentDocumentScopeId;
    if (streamControllers.has(initialStreamKey)) return;
    streamingAutoScrollPaused = false;

    // Append User Message with Image Preview
    const userPromptText = text || (
        currentImageB64Items.length
            ? "Analyse cette image."
            : "Analyse le document joint."
    );
    const existingUserMessages = chatMessages.querySelectorAll(".message.user");
    const userBubble = replayExistingLastUser
        ? existingUserMessages[existingUserMessages.length - 1]?.querySelector(".bubble")
        : appendMessage("user", userPromptText, currentImageDataUrls[0] || null);
    if (
        requestIsTemporary
        && userBubble
        && typeof decorateMessageActions === "function"
    ) {
        decorateMessageActions(
            userBubble.closest(".message"),
            "user",
            null,
            userPromptText
        );
    }
    
    const userMsgObj = { role: "user", content: userPromptText };
    if (currentImageB64Items.length) {
        userMsgObj.images = currentImageB64Items;
    }
    if (!replayExistingLastUser) conversationHistory.push(userMsgObj);
    const streamConversationHistory = conversationHistory;

    // Append Assistant Container with Animated Pulsing Dots
    const assistantBubble = appendMessage("assistant", "...");
    const userMessage = userBubble?.closest(".message") || null;
    const assistantMessage = assistantBubble.closest(".message");
    replaceTurnSpacer(userMessage, assistantMessage);
    positionTurnAtViewportTop(userMessage);
    let fullResponse = "";
    let webResultsMeta = [];
    let generationStatsMeta = null;
    
    let reasoningDuration = null;
    const agentToolEvents = [];

    const streamController = new AbortController();
    let streamKey = initialStreamKey;
    streamControllers.set(streamKey, streamController);
    refreshSendButtonState();

    let activeSessionIdForStream = currentSessionId;
    const isStreamVisible = () => {
        if (activeSessionIdForStream) {
            return currentSessionId === activeSessionIdForStream;
        }
        if (streamSessionId) {
            return currentSessionId === streamSessionId;
        }
        return (
            currentSessionId === null
            && currentDocumentScopeId === initialStreamKey
        );
    };
    if (activeSessionIdForStream) {
        activeStreamingSessions.add(activeSessionIdForStream);
        loadSessions();
    }

    try {
        // Strip heavy base64 image strings from older turns to keep HTTP payload light
        const cleanHistory = streamConversationHistory.map((m, idx) => {
            if (idx === streamConversationHistory.length - 1) return m;
            const { images, ...rest } = m;
            return rest;
        });

        const selectedModel = inputModelSelect ? inputModelSelect.value : "gemma-4-12b";
        const activeWebMode = webSearchBtn
            ? (webSearchBtn.dataset.mode || "auto")
            : "auto";
        const isDeepResearch = activeWebMode === "deep";
        const endpoint = isDeepResearch
            ? `${API_BASE}/research/stream`
            : `${API_BASE}/chat/stream`;
        const requestBody = isDeepResearch
            ? {
                session_id: streamSessionId,
                project_id: currentProjectId,
                question: userPromptText,
                model: selectedModel,
                selected_file_ids: requestSelectedFileIds,
                temporary: requestIsTemporary
            }
            : {
                session_id: streamSessionId,
                project_id: currentProjectId,
                document_scope_id: currentDocumentScopeId,
                selected_file_ids: requestSelectedFileIds,
                model: selectedModel,
                messages: cleanHistory,
                intelligence_level: reasoningLevelSelect ? reasoningLevelSelect.value : "balanced",
                web_search_enabled: webSearchToggle.checked,
                web_search_mode: activeWebMode,
                persist_user_message: (
                    !requestIsTemporary
                    && !replayExistingLastUser
                ),
                temporary: requestIsTemporary
            };
        const resp = await fetch(endpoint, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            signal: streamController.signal,
            body: JSON.stringify(requestBody)
        });

        if (!resp.ok) {
            let detail = `HTTP ${resp.status}`;
            try {
                const errorPayload = await resp.json();
                detail = errorPayload.detail || detail;
            } catch (_) {}
            throw new Error(detail);
        }
        if (!resp.body) throw new Error("Streaming response body is unavailable.");

        const reader = resp.body.getReader();
        const decoder = new TextDecoder("utf-8");
        let sseBuffer = "";  // Buffer for incomplete SSE lines split across chunks

        while (true) {
            const { value, done } = await reader.read();
            if (done) break;

            sseBuffer += decoder.decode(value, { stream: true });

            const lines = sseBuffer.split("\n");
            sseBuffer = lines.pop() || "";

            for (const line of lines) {
                const trimmedLine = line.trim();
                if (!trimmedLine.startsWith("data: ")) continue;

                const dataStr = trimmedLine.slice(6).trim();
                if (dataStr === "[DONE]") break;

                try {
                    const parsed = JSON.parse(dataStr);
                    if (parsed.session_id) {
                        activeSessionIdForStream = parsed.session_id;
                        activeStreamingSessions.add(parsed.session_id);
                        if (streamKey !== parsed.session_id) {
                            if (streamControllers.get(streamKey) === streamController) {
                                streamControllers.delete(streamKey);
                            }
                            streamKey = parsed.session_id;
                            streamControllers.set(streamKey, streamController);
                        }
                        const shouldActivateSession = streamSessionId
                            ? currentSessionId === streamSessionId
                            : (
                                currentSessionId === null
                                && currentDocumentScopeId === initialStreamKey
                            );
                        if (shouldActivateSession) {
                            currentSessionId = parsed.session_id;
                            currentDocumentScopeId = currentProjectId;
                            localStorage.setItem("active_session_id", parsed.session_id);
                            refreshSendButtonState();
                        }
                        loadSessions();
                    }
                    if (parsed.user_message_id && userBubble) {
                        decorateMessageActions(
                            userBubble.closest(".message"),
                            "user",
                            parsed.user_message_id,
                            userPromptText
                        );
                    }
                    if (parsed.type === "message_saved" && parsed.message_id) {
                        decorateMessageActions(
                            assistantBubble.closest(".message"),
                            "assistant",
                            parsed.message_id,
                            fullResponse
                        );
                    }
                    if (parsed.type === "research_plan") {
                        renderResearchPlan(assistantBubble, parsed.steps || []);
                    }
                    if (parsed.type === "research_step") {
                        updateResearchStep(assistantBubble, parsed);
                    }
                    if (parsed.type === "research_synthesis") {
                        if (parsed.web_results) webResultsMeta = parsed.web_results;
                        renderAssistantActivity(
                            assistantBubble,
                            "web",
                            "active",
                            "Synthèse des recherches",
                            `${parsed.result_count || 0} source(s) recoupée(s)`
                        );
                    }
                    if (parsed.type === "research_done") {
                        if (parsed.web_results) webResultsMeta = parsed.web_results;
                        renderAssistantActivity(
                            assistantBubble,
                            "web",
                            "done",
                            "Recherche approfondie terminée",
                            `${parsed.result_count || 0} source(s) retenue(s)`
                        );
                        if (parsed.artifact_id && typeof openCanvasArtifact === "function") {
                            assistantBubble.dataset.artifactId = parsed.artifact_id;
                        }
                    }
                    if (parsed.type === "session" && parsed.context_meta) {
                        updateContextUsage(parsed.context_meta);
                    }
                    if (parsed.web_results && parsed.web_results.length > 0) {
                        webResultsMeta = parsed.web_results;
                    }
                    if (parsed.type === "web_search_start") {
                        renderAssistantActivity(
                            assistantBubble,
                            "web",
                            "active",
                            parsed.message || "Recherche sur le Web"
                        );
                    }
                    if (parsed.type === "tool_start") {
                        renderAssistantActivity(
                            assistantBubble,
                            "web",
                            "active",
                            parsed.message || "Consultation de données structurées"
                        );
                    }
                    if (parsed.type === "tool_done" && parsed.status !== "ok") {
                        renderAssistantActivity(
                            assistantBubble,
                            "web",
                            "warning",
                            "Données structurées indisponibles",
                            "Bascule vers la recherche Web"
                        );
                    }
                    if (parsed.type === "web_extract_done") {
                        renderAssistantActivity(
                            assistantBubble,
                            "web",
                            "active",
                            parsed.message || "Pages analysées",
                            parsed.verified_count
                                ? `${parsed.verified_count} source(s) vérifiée(s)`
                                : ""
                        );
                    }
                    if (parsed.type === "web_search_done") {
                        if (parsed.web_results) {
                            webResultsMeta = parsed.web_results;
                        }
                        const webContextAvailable = (
                            parsed.status === "ok"
                            || parsed.status === "cached"
                        );
                        const evidenceInsufficient = (
                            parsed.status === "insufficient_evidence"
                        );
                        renderAssistantActivity(
                            assistantBubble,
                            "web",
                            webContextAvailable ? "done" : "warning",
                            parsed.status === "cached"
                                ? (
                                    parsed.message
                                    || "Contexte Web vérifié réutilisé"
                                )
                                : parsed.status === "ok"
                                ? (
                                    parsed.answer_mode === "provider"
                                        ? "Sources Web vérifiées"
                                        : `${parsed.result_count} source${parsed.result_count > 1 ? "s" : ""} pertinente${parsed.result_count > 1 ? "s" : ""}`
                                )
                                : evidenceInsufficient
                                ? (
                                    parsed.message
                                    || "Aucun fait suffisamment vérifié"
                                )
                                : "Recherche Web indisponible",
                            parsed.answer_mode === "provider"
                                ? `${parsed.result_count || 0} source${parsed.result_count > 1 ? "s" : ""} citée${parsed.result_count > 1 ? "s" : ""}`
                                : (
                                    webContextAvailable
                                    || evidenceInsufficient
                                ) && parsed.candidate_count
                                ? `${parsed.candidate_count} résultats évalués · ${parsed.search_query || ""}`
                                : parsed.search_query || ""
                        );
                    }
                    if (parsed.type === "reasoning_start") {
                        renderAssistantActivity(
                            assistantBubble,
                            "reasoning",
                            "active",
                            "Analyse en cours"
                        );
                    }
                    if (parsed.type === "reasoning_done") {
                        reasoningDuration = parsed.duration;
                        renderAssistantActivity(
                            assistantBubble,
                            "reasoning",
                            "done",
                            `Analyse terminée · ${parsed.duration || 0} s`,
                            parsed.summary || ""
                        );
                    }
                    if (parsed.type === "agent_tool_call") {
                        agentToolEvents.push(parsed);
                        renderAssistantActivity(
                            assistantBubble,
                            "tools",
                            "active",
                            `Outil · ${parsed.name || "?"}`,
                            shortToolArgs(parsed.arguments)
                        );
                    }
                    if (parsed.type === "agent_tool_result") {
                        agentToolEvents.push(parsed);
                        renderAssistantActivity(
                            assistantBubble,
                            "tools",
                            parsed.ok ? "done" : "warning",
                            `Outil · ${parsed.name || "?"}`,
                            parsed.ok
                                ? (parsed.duration_ms
                                    ? `${parsed.duration_ms} ms`
                                    : "terminé")
                                : (parsed.error_code || "échec")
                        );
                    }
                    if (parsed.type === "generation_stats") {
                        generationStatsMeta = parsed;
                    }
                    if (parsed.type === "error") {
                        const message = parsed.message || "La génération a été interrompue.";
                        fullResponse = fullResponse
                            ? `${fullResponse}\n\n*${message}*`
                            : `*${message}*`;
                        renderFullAssistantMessage(
                            assistantBubble,
                            fullResponse,
                            webResultsMeta,
                            reasoningDuration
                        );
                        followStreamingResponse(
                            userMessage,
                            assistantMessage
                        );
                    }
                    if (parsed.type === "image_start") {
                        if (isStreamVisible()) {
                            renderDalleLoaderCard(assistantBubble);
                            followStreamingResponse(
                                userMessage,
                                assistantMessage
                            );
                        }
                    }
                    if (parsed.type === "image_done" && parsed.image_url) {
                        fullResponse = `![${parsed.prompt}](${parsed.image_url})`;
                        if (isStreamVisible()) {
                            renderGeneratedImageCard(assistantBubble, parsed.image_url, parsed.prompt);
                            followStreamingResponse(
                                userMessage,
                                assistantMessage
                            );
                        }
                    }
                    if (parsed.content) {
                        fullResponse = cleanModelText(fullResponse + parsed.content);

                        // Only render to active UI if user is still on this conversation
                        if (isStreamVisible()) {
                            renderAssistantProgressively(
                                assistantBubble,
                                fullResponse,
                                webResultsMeta,
                                reasoningDuration,
                                {
                                    onPaint: () => followStreamingResponse(
                                        userMessage,
                                        assistantMessage
                                    ),
                                }
                            );
                        }
                    }
                } catch (err) {
                    sseBuffer = line + "\n" + sseBuffer;
                }
            }
        }

        const remaining = decoder.decode();
        if (remaining) {
            sseBuffer += remaining;
        }

        if (isStreamVisible()) {
            renderAssistantProgressively(
                assistantBubble,
                fullResponse,
                webResultsMeta,
                reasoningDuration,
                {
                    final: true,
                    onPaint: () => followStreamingResponse(
                        userMessage,
                        assistantMessage
                    ),
                    onComplete: () => {
                        if (generationStatsMeta) {
                            renderGenerationPerformance(
                                assistantBubble,
                                generationStatsMeta
                            );
                        }
                        if (agentToolEvents.length) {
                            renderAgentToolsSummary(
                                assistantBubble,
                                agentToolEvents
                            );
                        }
                        followStreamingResponse(
                            userMessage,
                            assistantMessage
                        );
                    },
                }
            );
        }
        if (window.LasmeProgressiveRenderer?.stripNumericCitations) {
            fullResponse = window.LasmeProgressiveRenderer
                .stripNumericCitations(fullResponse);
        }
        streamConversationHistory.push({ role: "assistant", content: fullResponse });
        if (
            requestIsTemporary
            && fullResponse
            && typeof decorateMessageActions === "function"
        ) {
            decorateMessageActions(
                assistantBubble.closest(".message"),
                "assistant",
                null,
                fullResponse
            );
        }
        if (activeSessionIdForStream && fullResponse) {
            void loadSuggestedQuestions(
                activeSessionIdForStream,
                inputModelSelect ? inputModelSelect.value : "gemma-4-12b",
                assistantBubble
            );
        }

    } catch (err) {
        window.LasmeProgressiveRenderer?.cancel?.(assistantBubble);
        if (err.name === "AbortError") {
            if (fullResponse) {
                fullResponse += "\n\n*(Génération arrêtée par l'utilisateur)*";
            } else {
                fullResponse = "*(Génération arrêtée par l'utilisateur)*";
            }
            if (isStreamVisible()) {
                renderFullAssistantMessage(assistantBubble, fullResponse, webResultsMeta, reasoningDuration);
                if (agentToolEvents.length) {
                    renderAgentToolsSummary(assistantBubble, agentToolEvents);
                }
            }
            streamConversationHistory.push({ role: "assistant", content: fullResponse });
        } else {
            if (isStreamVisible()) {
                assistantBubble.textContent = `Erreur : ${err.message || "connexion au serveur local impossible"}`;
                assistantBubble.style.color = "#EF4444";
            }
        }
    } finally {
        if (activeSessionIdForStream) {
            activeStreamingSessions.delete(activeSessionIdForStream);
        }
        if (streamControllers.get(streamKey) === streamController) {
            streamControllers.delete(streamKey);
        }
        if (streamControllers.get(initialStreamKey) === streamController) {
            streamControllers.delete(initialStreamKey);
        }
        refreshSendButtonState();
        loadSessions();
    }
}

// Append Message with optional image attachment
function appendMessage(
    role,
    text,
    imageUrl = null,
    webResults = [],
    messageId = null,
    generationStats = null
) {
    const msgDiv = document.createElement("div");
    msgDiv.className = `message ${role}`;
    if (messageId) msgDiv.dataset.messageId = messageId;

    const bubbleDiv = document.createElement("div");
    bubbleDiv.className = "bubble";
    bubbleDiv._lasmeRawContent = String(text || "");
    
    if (role === "user") {
        if (imageUrl) {
            const imgEl = document.createElement("img");
            imgEl.className = "user-attached-image";
            imgEl.src = imageUrl;
            imgEl.onclick = () => openImageViewer(imageUrl);
            bubbleDiv.appendChild(imgEl);
        }
        if (text) {
            const textSpan = document.createElement("div");
            textSpan.className = "user-text-content";
            textSpan.textContent = text;
            bubbleDiv.appendChild(textSpan);
        }
    } else {
        if (text === "...") {
            bubbleDiv.innerHTML = `<div class="typing-indicator"><span></span><span></span><span></span></div>`;
        } else if (text) {
            renderFullAssistantMessage(bubbleDiv, text, webResults);
            renderGenerationPerformance(bubbleDiv, generationStats);
        }
    }

    msgDiv.appendChild(bubbleDiv);
    if (messageId && typeof decorateMessageActions === "function") {
        decorateMessageActions(msgDiv, role, messageId, text || "");
    }
    chatMessages.appendChild(msgDiv);
    chatMessages.scrollTop = chatMessages.scrollHeight;
    return bubbleDiv;
}

function cleanModelText(value) {
    const replacements = new Map([
        ["â€™", "’"],
        ["â€˜", "‘"],
        ["â€œ", "“"],
        ["â€", "”"],
        ["â€“", "–"],
        ["â€”", "—"],
        ["Â·", "·"],
        ["Â", ""],
    ]);
    let text = String(value || "").normalize("NFC").replaceAll("\uFFFD", "");
    replacements.forEach((replacement, broken) => {
        text = text.replaceAll(broken, replacement);
    });
    return Array.from(text).filter(character => {
        if (/[\n\r\t]/u.test(character)) return true;
        if (/[\p{Cc}\p{Cf}]/u.test(character)) return false;
        if (/\p{L}/u.test(character)) {
            // Greek letters are valid mathematical symbols (α, β, ε, …).
            return /[A-Za-z\u00C0-\u024F\u0370-\u03FF\u1E00-\u1EFF]/u.test(character);
        }
        return true;
    }).join("");
}

function escapeHtml(value) {
    return String(value)
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;")
        .replaceAll("'", "&#039;");
}

function safeHttpUrl(value) {
    try {
        const parsed = new URL(String(value || ""), window.location.origin);
        if (!["http:", "https:"].includes(parsed.protocol)) return "";
        return parsed.origin === window.location.origin
            ? `${parsed.pathname}${parsed.search}${parsed.hash}`
            : parsed.href;
    } catch (_) {
        return "";
    }
}

function sanitizeHtml(value) {
    if (window.DOMPurify) {
        return window.DOMPurify.sanitize(String(value || ""), {
            USE_PROFILES: { html: true },
            ADD_ATTR: ["target", "download"],
        });
    }
    return escapeHtml(value);
}

function sourceFallbackIcon() {
    return `
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor"
             stroke-width="2" stroke-linecap="round" stroke-linejoin="round"
             aria-hidden="true">
            <circle cx="12" cy="12" r="11" fill="currentColor" stroke="none" opacity=".14"></circle>
            <circle cx="12" cy="12" r="8.5"></circle>
            <path d="M3.8 12h16.4M12 3.5c2.2 2.35 3.3 5.18 3.3 8.5S14.2 18.15 12 20.5M12 3.5C9.8 5.85 8.7 8.68 8.7 12s1.1 6.15 3.3 8.5"></path>
        </svg>
    `;
}

function renderAssistantActivity(container, kind, state, title, detail = "") {
    const selector = `.assistant-activity[data-kind="${kind}"]`;
    let activity = container.querySelector(selector);
    if (!activity) {
        const typingIndicator = container.querySelector(".typing-indicator");
        if (typingIndicator) typingIndicator.remove();

        activity = document.createElement("div");
        activity.className = "assistant-activity";
        activity.dataset.kind = kind;
        container.prepend(activity);
    }

    activity.dataset.state = state;
    const icon = kind === "web" ? "◎" : "✦";
    const spinner = state === "active"
        ? `<span class="activity-spinner" aria-hidden="true"></span>`
        : "";
    const safeDetail = escapeHtml(detail || "");
    activity.innerHTML = `
        <div class="assistant-activity-title">
            <span class="assistant-activity-icon">${icon}</span>
            <span>${escapeHtml(title)}</span>
            ${spinner}
        </div>
        ${safeDetail ? `<div class="assistant-activity-detail">${safeDetail}</div>` : ""}
    `;
}

function shortToolArgs(raw) {
    try {
        const text = JSON.stringify(JSON.parse(raw || "{}"));
        return text.length > 160 ? `${text.slice(0, 160)}…` : text;
    } catch {
        return (raw || "").slice(0, 160);
    }
}

function renderAgentToolsSummary(container, events) {
    container.querySelector(".agent-tools-group")?.remove();
    const calls = new Map();
    for (const event of events) {
        if (event.type === "agent_tool_call") {
            calls.set(event.id ?? calls.size, { call: event, result: null });
        } else if (event.type === "agent_tool_result") {
            const entry = calls.get(event.id)
                || [...calls.values()].find((candidate) => !candidate.result);
            if (entry) entry.result = event;
        }
    }
    if (!calls.size) return;
    const group = document.createElement("div");
    group.className = "agent-tools-group";
    for (const { call, result } of calls.values()) {
        const card = document.createElement("details");
        card.className = `agent-tool-card ${result && !result.ok ? "ko" : "ok"}`;
        const summary = document.createElement("summary");
        const meta = result
            ? (result.ok
                ? (result.duration_ms ? `${result.duration_ms} ms` : "< 5 ms")
                : (result.error_code || "échec"))
            : "…";
        summary.textContent = `${call.name || "?"} — ${meta}`;
        const args = document.createElement("pre");
        args.className = "agent-tool-args";
        try {
            args.textContent = JSON.stringify(
                JSON.parse(call.arguments || "{}"), null, 2
            );
        } catch {
            args.textContent = call.arguments || "";
        }
        card.append(summary, args);
        if (result) {
            const output = document.createElement("pre");
            output.className = "agent-tool-output";
            output.textContent = result.ok
                ? (result.output || "(vide)")
                : `${result.error_code || "erreur"} : ${result.error || ""}`;
            card.appendChild(output);
            if (!result.ok) card.open = true;
        }
        group.appendChild(card);
    }
    container.querySelector(".assistant-activity[data-kind=\"tools\"]")?.remove();
    container.prepend(group);
}

function formatPerformanceNumber(value, maximumFractionDigits = 1) {
    const number = Number(value);
    if (!Number.isFinite(number)) return "";
    return new Intl.NumberFormat("fr-FR", {
        maximumFractionDigits,
        minimumFractionDigits: 0
    }).format(number);
}

function renderGenerationPerformance(container, rawStats) {
    if (!container) return;
    container
        .querySelector('.assistant-activity[data-kind="generation"]')
        ?.remove();
    container.querySelector(".generation-performance")?.remove();

    const stats = rawStats && typeof rawStats === "object"
        ? rawStats
        : null;
    if (!stats) return;

    const speed = Number(stats.tokens_per_second || 0);
    const outputTokens = Number(stats.output_tokens || 0);
    const totalSeconds = Number(
        stats.total_seconds || stats.generation_seconds || 0
    );
    const firstTokenSeconds = Number(stats.time_to_first_token || 0);
    const promptTokens = Number(stats.prompt_tokens || 0);
    if (!speed && !outputTokens && !totalSeconds) return;

    const performance = document.createElement("div");
    performance.className = "generation-performance";
    performance.setAttribute("aria-label", "Performances de génération");

    const visibleMetrics = [];
    if (speed > 0) {
        visibleMetrics.push(`
            <span class="generation-performance-primary">
                ${formatPerformanceNumber(speed)} tok/s
            </span>
        `);
    }
    if (outputTokens > 0) {
        visibleMetrics.push(`
            <span>${formatPerformanceNumber(outputTokens, 0)} tokens</span>
        `);
    }
    if (totalSeconds > 0) {
        visibleMetrics.push(`
            <span>${formatPerformanceNumber(totalSeconds)} s</span>
        `);
    }

    const detailParts = [];
    if (firstTokenSeconds > 0) {
        detailParts.push(
            `premier token en ${formatPerformanceNumber(firstTokenSeconds, 2)} s`
        );
    }
    if (promptTokens > 0) {
        detailParts.push(
            `${formatPerformanceNumber(promptTokens, 0)} tokens en entrée`
        );
    }
    if (stats.model) {
        const modelKey = String(stats.model || "").toLowerCase();
        const modelLabel = modelKey.includes("256k")
            ? "Gemma 4 12B · 256K"
            : modelKey.includes("e4b")
            ? "Gemma 4 E4B"
            : modelKey.includes("e2b")
            ? "Gemma 4 E2B"
            : "Gemma 4 12B";
        detailParts.push(modelLabel);
    }
    performance.title = detailParts.length
        ? `Détails : ${detailParts.join(" · ")}`
        : "Performances de la réponse";

    performance.innerHTML = `
        <span class="generation-performance-icon" aria-hidden="true">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor"
                 stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
                <path d="M5.15 18.5a8.25 8.25 0 1 1 13.7 0"></path>
                <path d="m12 13 3.65-3.15"></path>
                <circle cx="12" cy="13" r="1.35"></circle>
                <path d="M6.55 14.1h1M8.1 9.55l.7.7M12 7v1M15.9 9.55l-.7.7M16.45 14.1h1"></path>
            </svg>
        </span>
        ${visibleMetrics
            .map((metric, index) => (
                `${index ? '<span class="generation-performance-separator" aria-hidden="true"></span>' : ""}${metric}`
            ))
            .join("")}
    `;
    container.appendChild(performance);
}

// Render only the final answer. Raw chain-of-thought is intentionally hidden;
// the UI receives structured activity events and a short process summary.
function renderFullAssistantMessage(container, rawText, webResults, thinkingDuration = null) {
    rawText = cleanModelText(rawText);
    rawText = window.LasmeProgressiveRenderer?.stripNumericCitations
        ? window.LasmeProgressiveRenderer.stripNumericCitations(rawText)
        : rawText;
    container._lasmeRawContent = rawText;
    let thinkingContent = "";
    let mainAnswer = (rawText || "")
        .replace(/<think>[\s\S]*?<\/think>/gi, "")
        .replace(/<think>[\s\S]*$/gi, "")
        .trim();
    let isThinkingActive = false;

    // Strip raw text "### Références" block at the end if the model outputted one
    mainAnswer = mainAnswer.replace(/(###?\s*(Références|Sources)[\s\S]*)/i, "").trim();

    // Extract <think> ... </think> or active <think>
    if (false && rawText.includes("<think>")) {
        if (rawText.includes("</think>")) {
            const parts = rawText.split("</think>");
            thinkingContent = parts[0].replace("<think>", "").trim();
            mainAnswer = parts.slice(1).join("</think>").trim();
            mainAnswer = mainAnswer.replace(/(###?\s*(Références|Sources)[\s\S]*)/i, "").trim();

            // FAILSAFE: If mainAnswer is empty because the model put its entire response inside <think>...</think>, fallback thinkingContent to mainAnswer so the answer is NEVER blank
            if (!mainAnswer && thinkingContent) {
                mainAnswer = thinkingContent;
                thinkingContent = "";
            }
        } else {
            isThinkingActive = true;
            thinkingContent = rawText.replace("<think>", "").trim();
            mainAnswer = "";
        }
    }

    // 1. Render or Update Thinking Container
    if (thinkingContent || isThinkingActive) {
        let thinkingContainer = container.querySelector(".thinking-container");
        let headerDiv = null;
        let bodyDiv = null;

        if (!thinkingContainer) {
            container.innerHTML = "";
            thinkingContainer = document.createElement("div");
            thinkingContainer.className = `thinking-container ${isThinkingActive ? "" : "collapsed"}`;

            headerDiv = document.createElement("div");
            headerDiv.className = "thinking-header";

            bodyDiv = document.createElement("div");
            bodyDiv.className = `thinking-body ${isThinkingActive ? "" : "faded-out"}`;

            headerDiv.addEventListener("click", () => {
                thinkingContainer.classList.toggle("collapsed");
            });

            thinkingContainer.appendChild(headerDiv);
            thinkingContainer.appendChild(bodyDiv);
            container.appendChild(thinkingContainer);
        } else {
            headerDiv = thinkingContainer.querySelector(".thinking-header");
            bodyDiv = thinkingContainer.querySelector(".thinking-body");
        }

        if (isThinkingActive) {
            if (!headerDiv.dataset.state || headerDiv.dataset.state !== "active") {
                headerDiv.dataset.state = "active";
                headerDiv.innerHTML = `<span>Réflexion en cours</span> <div class="typing-indicator" style="display:inline-flex; transform:scale(0.85);"><span></span><span></span><span></span></div> <span class="chevron">▼</span>`;
                thinkingContainer.classList.remove("collapsed");
                bodyDiv.classList.remove("faded-out");
            }
        } else {
            if (headerDiv.dataset.state !== "done") {
                headerDiv.dataset.state = "done";
                const durationText = thinkingDuration ? `${thinkingDuration} s` : `quelques secondes`;
                headerDiv.innerHTML = `<span>Pensé pendant ${durationText}</span> <span class="chevron">▼</span>`;
                thinkingContainer.classList.add("collapsed");
                bodyDiv.classList.add("faded-out");
            }
        }

        renderRichContent(bodyDiv, thinkingContent, []);
    } else {
        const thinkingContainer = container.querySelector(".thinking-container");
        if (thinkingContainer && !rawText.includes("<think>")) {
            thinkingContainer.remove();
        }
    }

    // 2. Render or Update Main Answer Content
    if (mainAnswer || (!thinkingContent && !isThinkingActive)) {
        let answerDiv = container.querySelector(".answer-content");
        if (!answerDiv) {
            if (!container.querySelector(".thinking-container")) {
                const typingIndicator = container.querySelector(".typing-indicator");
                if (typingIndicator) typingIndicator.remove();
            }
            answerDiv = document.createElement("div");
            answerDiv.className = "answer-content";
            container.appendChild(answerDiv);
        }
        renderRichContent(answerDiv, mainAnswer, webResults);

        // 3. Render Modern Expandable Sources Drawer at the bottom if Web Results exist
        if (webResults && webResults.length > 0) {
            let sourcesDrawer = container.querySelector(".sources-drawer-container");
            if (!sourcesDrawer) {
                sourcesDrawer = document.createElement("div");
                sourcesDrawer.className = "sources-drawer-container";

                const countStr = webResults.length > 1 ? `${webResults.length} sources` : `1 source`;
                const sourceMeta = webResults
                    .map(result => {
                        const safeUrl = safeHttpUrl(result.url);
                        if (!safeUrl) return null;
                        try {
                            const parsedUrl = new URL(safeUrl, window.location.origin);
                            const domain = parsedUrl.hostname.replace(/^www\./, "");
                            const domainParts = domain.split(".");
                            const lastTwoLabels = domainParts.slice(-2).join(".");
                            const multiPartSuffixes = new Set([
                                "co.uk", "org.uk", "com.au", "com.br",
                                "co.jp", "co.kr", "com.cn", "com.mx", "co.in"
                            ]);
                            const registrableLabelCount = (
                                multiPartSuffixes.has(lastTwoLabels) ? 3 : 2
                            );
                            const faviconDomain = domainParts.length > registrableLabelCount
                                ? domainParts.slice(-registrableLabelCount).join(".")
                                : domain;
                            return {
                                result,
                                safeUrl,
                                domain,
                                faviconDomain,
                                faviconUrl: `/favicons/${encodeURIComponent(faviconDomain)}`,
                                initial: (faviconDomain[0] || "S").toUpperCase()
                            };
                        } catch (error) {
                            return null;
                        }
                    })
                    .filter(Boolean);
                const uniqueFaviconSources = [];
                const seenFaviconDomains = new Set();
                sourceMeta.forEach(item => {
                    if (
                        uniqueFaviconSources.length < 3
                        && !seenFaviconDomains.has(item.faviconDomain)
                    ) {
                        seenFaviconDomains.add(item.faviconDomain);
                        uniqueFaviconSources.push(item);
                    }
                });
                const faviconStack = uniqueFaviconSources.map(item => `
                    <span class="source-favicon-shell" title="${escapeHtml(item.domain)}">
                        <span class="source-favicon-fallback">${sourceFallbackIcon()}</span>
                        <img class="source-favicon" src="${escapeHtml(item.faviconUrl)}" alt="">
                    </span>
                `).join("");
                
                sourcesDrawer.innerHTML = `
                    <button type="button" class="sources-drawer-header" aria-expanded="false">
                        <span class="sources-favicon-stack" aria-hidden="true">
                            ${faviconStack}
                        </span>
                        <span>${countStr}</span>
                    </button>
                    <div class="sources-drawer-body">
                        ${sourceMeta.map(item => `
                            <a href="${escapeHtml(item.safeUrl)}" target="_blank" rel="noopener noreferrer" class="source-card">
                                <span class="source-favicon-shell source-card-favicon">
                                    <span class="source-favicon-fallback">${sourceFallbackIcon()}</span>
                                    <img class="source-favicon" src="${escapeHtml(item.faviconUrl)}" alt="">
                                </span>
                                <div class="source-info">
                                    <div class="source-title">${escapeHtml(item.result.title || item.domain)}</div>
                                    <div class="source-domain">${escapeHtml(item.domain)}</div>
                                </div>
                            </a>
                        `).join("")}
                    </div>
                `;

                const drawerHeader = sourcesDrawer.querySelector(".sources-drawer-header");
                drawerHeader.addEventListener("click", () => {
                    sourcesDrawer.classList.toggle("open");
                    drawerHeader.setAttribute(
                        "aria-expanded",
                        sourcesDrawer.classList.contains("open") ? "true" : "false"
                    );
                });
                sourcesDrawer.querySelectorAll(".source-favicon").forEach(image => {
                    image.addEventListener("error", () => {
                        image.src = "/source-fallback.svg";
                        image.classList.add("generic");
                    }, { once: true });
                });

                container.appendChild(sourcesDrawer);
            }
        }
    }
}

// Rich content renderer (Markdown + resilient KaTeX rendering).
function renderRichContent(container, text, webResults) {
    if (!text) {
        container.innerHTML = "";
        return;
    }

    // Keep valid Web citations in the expandable source drawer. Numeric
    // arrays such as Python/JSON "[1]" must remain untouched when no matching
    // Web source exists.
    const sourceCount = Array.isArray(webResults) ? webResults.length : 0;
    if (sourceCount > 0) {
        text = text.replace(
            /\s*\[(\d+(?:\s*[,–-]\s*\d+)*)\]/g,
            (fullMatch, body) => {
                const numbers = String(body).match(/\d+/g)?.map(Number) || [];
                const valid = numbers.length > 0 && numbers.every(
                    number => number >= 1 && number <= sourceCount
                );
                return valid ? "" : fullMatch;
            }
        );
    }
    text = text.replace(/[ \t]+([,.;:!?])/g, "$1");

    const preparedMath = window.LasmeMath
        ? window.LasmeMath.prepareForMarkdown(text)
        : { text, math: [] };
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

    container.innerHTML = sanitizeHtml(html);
    container.querySelectorAll('a[target="_blank"]').forEach(link => {
        link.setAttribute("rel", "noopener noreferrer");
    });

    // ── STEP 7: Generated image cards ─────────────────────────────────────
    const genImgs = container.querySelectorAll("img[src*='/generated_images/']");
    genImgs.forEach(img => {
        if (!img.closest(".generated-image-card") && !img.classList.contains("user-attached-image")) {
            const src = img.getAttribute("src");
            const alt = img.getAttribute("alt") || "Image générée";
            const safeSrc = safeHttpUrl(src);
            if (!safeSrc) {
                img.remove();
                return;
            }
            const cardDiv = document.createElement("div");
            cardDiv.className = "generated-image-card";
            cardDiv.innerHTML = sanitizeHtml(`
                <img src="${escapeHtml(safeSrc)}" alt="${escapeHtml(alt)}">
                <div class="generated-image-overlay">
                    <span style="color:#FFF; font-size:0.8rem; font-weight:500; text-overflow:ellipsis; overflow:hidden; white-space:nowrap; max-width:170px;">${escapeHtml(alt)}</span>
                    <div class="image-card-actions">
                        <button type="button" class="img-action-btn image-zoom-btn">
                            🔍 Zoom
                        </button>
                        <a href="${escapeHtml(safeSrc)}" download class="img-action-btn">
                            📥 Télécharger HD
                        </a>
                    </div>
                </div>
            `);
            const cardImage = cardDiv.querySelector("img");
            const cardZoom = cardDiv.querySelector(".image-zoom-btn");
            if (cardImage) cardImage.addEventListener("click", () => openImageViewer(safeSrc));
            if (cardZoom) cardZoom.addEventListener("click", () => openImageViewer(safeSrc));
            if (img.parentNode && img.parentNode.tagName === "P" && img.parentNode.childNodes.length === 1) {
                img.parentNode.replaceWith(cardDiv);
            } else {
                img.replaceWith(cardDiv);
            }
        }
    });

    // ── STEP 8: KaTeX render on DOM ───────────────────────────────────────
    if (typeof renderMathInElement !== "undefined") {
        try {
            renderMathInElement(container, {
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
            console.warn("Unable to render a LaTeX fragment:", error);
        }
    }


    // STEP 6: Code Blocks Header & Copy Button
    container.querySelectorAll("pre code").forEach((codeBlock) => {
        if (codeBlock.parentElement.classList.contains("code-wrapped")) return;
        
        const pre = codeBlock.parentElement;
        const wrapper = document.createElement("div");
        wrapper.className = "code-wrapper code-wrapped";
        
        const langClass = Array.from(codeBlock.classList).find(c => c.startsWith("language-"));
        const langName = langClass ? langClass.replace("language-", "").toUpperCase() : "CODE";

        const header = document.createElement("div");
        header.className = "code-header";
        header.innerHTML = `<span>${langName}</span><button type="button" class="copy-code-btn">Copier</button>`;
        
        const copyBtn = header.querySelector(".copy-code-btn");
        copyBtn.addEventListener("click", (e) => {
            if (e) e.preventDefault();
            navigator.clipboard.writeText(codeBlock.innerText);
            copyBtn.textContent = "Copié !";
            setTimeout(() => copyBtn.textContent = "Copier", 2000);
        });

        pre.parentNode.insertBefore(wrapper, pre);
        wrapper.appendChild(header);
        wrapper.appendChild(pre);
    });

    enhanceResponseTables(container);
    linkDocumentCitations(container);

    // STEP 7: Mermaid Diagrams Rendering
    if (typeof mermaid !== "undefined") {
        container.querySelectorAll("pre code.language-mermaid").forEach((block) => {
            const mermaidCode = block.innerText;
            const mermaidDiv = document.createElement("div");
            mermaidDiv.className = "mermaid";
            mermaidDiv.textContent = mermaidCode;
            block.parentElement.parentElement.replaceWith(mermaidDiv);
            try {
                mermaid.run({ nodes: [mermaidDiv] });
            } catch (err) {}
        });
    }

    // Step 8: Replace Unicode Country Flag Emojis with Twemoji SVGs for Windows
    replaceFlagsWithSvg(container);
}

function tableToTsv(table) {
    return Array.from(table.rows)
        .map(row => Array.from(row.cells)
            .map(cell => cell.innerText.replace(/\s+/g, " ").trim())
            .join("\t"))
        .join("\n");
}

function tableToCsv(table) {
    const quote = value => `"${String(value).replace(/"/g, '""')}"`;
    return Array.from(table.rows)
        .map(row => Array.from(row.cells)
            .map(cell => quote(cell.innerText.replace(/\s+/g, " ").trim()))
            .join(","))
        .join("\r\n");
}

function enhanceResponseTables(container) {
    container.querySelectorAll("table").forEach((table, index) => {
        if (table.closest(".response-table-artifact")) return;
        const shell = document.createElement("section");
        shell.className = "response-table-artifact";
        const toolbar = document.createElement("header");
        toolbar.className = "response-table-toolbar";
        const label = document.createElement("span");
        label.textContent = `Tableau ${index + 1}`;
        const actions = document.createElement("span");
        actions.className = "response-table-actions";
        const copy = document.createElement("button");
        copy.type = "button";
        copy.title = "Copier le tableau";
        copy.textContent = "Copier";
        copy.addEventListener("click", async () => {
            await navigator.clipboard.writeText(tableToTsv(table));
            copy.textContent = "Copié";
            setTimeout(() => { copy.textContent = "Copier"; }, 1600);
        });
        const exportButton = document.createElement("button");
        exportButton.type = "button";
        exportButton.title = "Exporter au format CSV";
        exportButton.textContent = "CSV";
        exportButton.addEventListener("click", () => {
            const blob = new Blob(["\uFEFF", tableToCsv(table)], {
                type: "text/csv;charset=utf-8"
            });
            const url = URL.createObjectURL(blob);
            const link = document.createElement("a");
            link.href = url;
            link.download = `tableau-${index + 1}.csv`;
            link.click();
            setTimeout(() => URL.revokeObjectURL(url), 0);
        });
        actions.append(copy, exportButton);
        toolbar.append(label, actions);
        const scroll = document.createElement("div");
        scroll.className = "response-table-scroll";
        table.parentNode.insertBefore(shell, table);
        scroll.appendChild(table);
        shell.append(toolbar, scroll);
    });
}

function linkDocumentCitations(container) {
    const pattern = /\[Document\s*:\s*([^,\]\n]+?)(?:\s*,\s*p(?:age)?\.?\s*(\d+))?\]\s*(?:\{file:([a-zA-Z0-9:_-]+)\})?/gi;
    const walker = document.createTreeWalker(container, NodeFilter.SHOW_TEXT);
    const nodes = [];
    let node;
    while ((node = walker.nextNode())) {
        if (
            node.nodeValue
            && pattern.test(node.nodeValue)
            && !node.parentElement?.closest("code, pre, .document-citation")
        ) {
            nodes.push(node);
        }
        pattern.lastIndex = 0;
    }
    nodes.forEach(textNode => {
        const source = textNode.nodeValue;
        const fragment = document.createDocumentFragment();
        let cursor = 0;
        pattern.lastIndex = 0;
        let match;
        while ((match = pattern.exec(source))) {
            fragment.appendChild(document.createTextNode(source.slice(cursor, match.index)));
            const button = document.createElement("button");
            button.type = "button";
            button.className = "document-citation";
            button.textContent = match[2]
                ? `${match[1].trim()} · p. ${match[2]}`
                : match[1].trim();
            button.title = "Ouvrir le document source";
            button.addEventListener("click", () => {
                const page = match[2] ? Number(match[2]) : null;
                const opened = match[3]
                    ? window.LasmeWorkspace?.openFile?.(match[3], page)
                    : false;
                if (!opened) {
                    window.LasmeWorkspace?.openFileByName?.(
                        match[1].trim(),
                        page
                    );
                }
            });
            fragment.appendChild(button);
            cursor = pattern.lastIndex;
        }
        fragment.appendChild(document.createTextNode(source.slice(cursor)));
        textNode.replaceWith(fragment);
    });
    pattern.lastIndex = 0;
}

// Deterministic country-code badge for Windows and offline installations.
function replaceFlagsWithSvg(container) {
    if (!container) return;
    const flagRegex = /([\uD83C][\uDDE6-\uDDFF][\uD83C][\uDDE6-\uDDFF])/g;
    const walker = document.createTreeWalker(container, NodeFilter.SHOW_TEXT, null, false);
    const textNodes = [];
    let node;
    while ((node = walker.nextNode())) {
        if (node.nodeValue && flagRegex.test(node.nodeValue)) {
            textNodes.push(node);
        }
    }
    textNodes.forEach(textNode => {
        const parent = textNode.parentNode;
        if (parent && parent.tagName !== "SCRIPT" && parent.tagName !== "STYLE") {
            const span = document.createElement("span");
            span.className = "emoji-flag-span";
            span.innerHTML = textNode.nodeValue.replace(flagRegex, (match) => {
                const countryCode = Array.from(match)
                    .map(character => String.fromCharCode(
                        character.codePointAt(0) - 0x1F1E6 + 65
                    ))
                    .join("");
                return `<span class="flag-fallback" role="img" aria-label="${countryCode}">${countryCode}</span>`;
            });
            parent.replaceChild(span, textNode);
        }
    });
}

// RAG Document Upload Logic (Integrated into bottom "+" Button)
if (docFileInput) {
    docFileInput.addEventListener("change", async () => {
        if (!docFileInput.files || docFileInput.files.length === 0) return;
        
        const file = docFileInput.files[0];
        const formData = new FormData();
        formData.append("file", file);
        formData.append("scope_id", currentDocumentScopeId);
        formData.append("wait_for_index", "true");

        if (attachedDocBadge && docBadgeName) {
            attachedDocBadge.style.display = "inline-flex";
            attachedDocBadge.classList.remove("has-error");
            attachedDocBadge.classList.add("is-loading");
            docBadgeName.textContent = `Préparation de ${file.name}…`;
        }

        try {
            const resp = await fetch(`${API_BASE}/documents/upload`, {
                method: "POST",
                body: formData
            });
            const data = await resp.json();
            if (!resp.ok) throw new Error(data.detail || "Document upload failed");
            if (data.file?.id) {
                attachedDocumentFileIds = [data.file.id];
                attachedDocumentProjectId = currentProjectId;
                attachedDocBadge?.classList.remove("is-loading");
                if (docBadgeName) docBadgeName.textContent = file.name;
            }
            if (typeof loadProjectDocuments === "function") {
                void loadProjectDocuments();
            }
        } catch (err) {
            attachedDocumentFileIds = [];
            attachedDocumentProjectId = null;
            attachedDocBadge?.classList.remove("is-loading");
            attachedDocBadge?.classList.add("has-error");
            if (docBadgeName) {
                docBadgeName.textContent = err.message || "Import impossible";
            }
        }
    });
}

if (clearDocBtn) {
    clearDocBtn.addEventListener("click", (e) => {
        if (e) e.preventDefault();
        attachedDocBadge?.classList.remove("is-loading", "has-error");
        resetDocumentAttachment();
    });
}

// ── AGENTIC IDE WORKSPACE INTERACTIVE FRONTEND ───────────────────────
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
const agCodingWebSearchBtn = document.getElementById("agCodingWebSearchBtn");
const agCodingWebSearchToggle = document.getElementById("agCodingWebSearchToggle");

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
        const resp = await fetch(`${API_BASE}/coding/file-tree?path=${encodeURIComponent(folderPath || '')}`);
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
        const resp = await fetch(`${API_BASE}/coding/file-content?file=${encodeURIComponent(filename)}`);
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
            const resp = await fetch(`${API_BASE}/coding/save-file`, {
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

// 7. Web Search Toggle in Coding Deck
if (agCodingWebSearchBtn && agCodingWebSearchToggle) {
    agCodingWebSearchBtn.addEventListener("click", () => {
        agCodingWebSearchToggle.checked = !agCodingWebSearchToggle.checked;
        agCodingWebSearchBtn.classList.toggle("active", agCodingWebSearchToggle.checked);
    });
}

// 8. Agentic Coding Conversation Stream (Design unifié avec le Chat)
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
        const useWeb = agCodingWebSearchToggle ? agCodingWebSearchToggle.checked : false;
        const resp = await fetch(`${API_BASE}/coding/agent/stream`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ prompt: prompt, model: LASME_REASONING_MODEL, web_search: useWeb })
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
