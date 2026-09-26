// Extrait verbatim de app.js (découpage modulaire).
// Script classique : les déclarations de top-level restent globales.
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
            try { localStorage.setItem("lasme_model_choice", modelVal); } catch (_) {}
            
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

// Choix persistant : le modèle choisi par l'utilisateur survit aux
// rechargements de page (au lieu de revenir au défaut du HTML).
try {
    const savedModel = localStorage.getItem("lasme_model_choice");
    if (savedModel) {
        document.querySelector(
            `#modelPickerDropdown .intel-option[data-model="${CSS.escape(savedModel)}"]`
        )?.click();
    }
} catch (_) {}

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
    const effortSlider = document.getElementById("effortSlider");
    const effortSliderDesc = document.getElementById("effortSliderDesc");
    const EFFORT_LEVELS = ["low", "medium", "high"];
    const EFFORT_DESCRIPTIONS = {
        low: "Réponses rapides, réflexion légère — idéal pour les échanges simples",
        medium: "Équilibre entre vitesse et profondeur d'analyse",
        high: "Analyse approfondie pour les demandes complexes",
    };

    window.setEffortLevel = function setEffortLevel(level) {
        const safe = EFFORT_LEVELS.includes(level) ? level : "high";
        reasoningLevelSelect.value = safe;
        try { localStorage.setItem("lasme_effort_choice", safe); } catch (_) {}
        if (selectedReasoningName) {
            selectedReasoningName.textContent = safe.charAt(0).toUpperCase() + safe.slice(1);
        }
        if (effortSlider) {
            effortSlider.dataset.value = safe;
            effortSlider.querySelectorAll(".effort-seg").forEach(seg => {
                const active = seg.dataset.level === safe;
                seg.classList.toggle("effort-seg-active", active);
                seg.setAttribute("aria-checked", active ? "true" : "false");
            });
        }
        if (effortSliderDesc) {
            effortSliderDesc.textContent = EFFORT_DESCRIPTIONS[safe];
        }
    };

    if (effortSlider) {
        effortSlider.querySelectorAll(".effort-seg").forEach(seg => {
            seg.addEventListener("click", e => {
                e.stopPropagation();
                setEffortLevel(seg.dataset.level);
            });
        });
        effortSlider.addEventListener("keydown", e => {
            const index = EFFORT_LEVELS.indexOf(effortSlider.dataset.value);
            if (e.key === "ArrowRight" && index < EFFORT_LEVELS.length - 1) {
                e.preventDefault();
                setEffortLevel(EFFORT_LEVELS[index + 1]);
            } else if (e.key === "ArrowLeft" && index > 0) {
                e.preventDefault();
                setEffortLevel(EFFORT_LEVELS[index - 1]);
            }
        });
        // Défaut au lancement : le dernier choix de l'utilisateur, sinon
        // Medium (standard mondial).
        let savedEffort = "medium";
        try {
            const stored = localStorage.getItem("lasme_effort_choice");
            if (EFFORT_LEVELS.includes(stored)) savedEffort = stored;
        } catch (_) {}
        setEffortLevel(savedEffort);
    }
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
