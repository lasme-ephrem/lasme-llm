// Extrait verbatim de app.js (découpage modulaire — voir ROADMAP.md, C1).
// Script classique : les déclarations de top-level restent globales.
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
