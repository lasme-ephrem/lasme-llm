// Extrait verbatim de app.js (découpage modulaire).
// Script classique : les déclarations de top-level restent globales.
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
