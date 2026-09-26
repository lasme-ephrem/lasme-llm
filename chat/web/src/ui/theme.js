// Extrait verbatim de app.js (découpage modulaire).
// Script classique : les déclarations de top-level restent globales.
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
                menuAttachImageBtn.title = "Aucun modèle de vision configuré";
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

