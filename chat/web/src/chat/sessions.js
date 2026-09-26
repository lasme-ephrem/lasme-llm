// Extrait verbatim de app.js (découpage modulaire).
// Script classique : les déclarations de top-level restent globales.
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
    releaseOutgoingLiveBubbleTimers();
    temporaryChatEnabled = false;
    updateTemporaryChatUI();
    resetDocumentAttachment();
    currentSessionId = sessionId;
    refreshSendButtonState();
    localStorage.setItem("active_session_id", sessionId);
    conversationHistory = [];
    if (chatMessages) chatMessages.innerHTML = "";
    const live = liveStreams.get(sessionId) || null;
    const liveActive = Boolean(live && !live.done);

    try {
        const resp = await fetch(`${API_BASE}/sessions/${sessionId}/messages`);
        if (!resp.ok) {
            if (liveActive) {
                renderLiveSessionFromStore(live);
            } else {
                startNewChat();
            }
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
            if (liveActive) {
                renderLiveSessionFromStore(live);
            } else {
                startNewChat();
            }
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
            const bubble = appendMessage(
                msg.role,
                cleanText,
                imgUrl,
                msg.metadata?.web_results || [],
                msg.id,
                msg.metadata?.generation_stats || null
            );
            if (msg.role === "assistant" && msg.metadata?.agent?.run_id) {
                addAgentReplayAction(
                    bubble.closest(".message"),
                    msg.metadata.agent
                );
            }
            conversationHistory.push({ role: msg.role, content: msg.content });
        });

        if (liveActive) {
            const lastEntry = conversationHistory[conversationHistory.length - 1];
            const userAlreadyShown = lastEntry?.role === "user"
                && (!live.userText
                    || String(lastEntry.content || "").includes(live.userText));
            renderLiveTurn(live, userAlreadyShown);
        }

        void loadSessions();
    } catch (err) {
        console.error("Erreur lecture messages session:", err);
        if (liveActive) {
            renderLiveSessionFromStore(live);
        } else {
            startNewChat();
        }
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
    releaseOutgoingLiveBubbleTimers();
    const nextTemporaryState = Boolean(options.temporary);
    if (temporaryChatEnabled && !nextTemporaryState) {
        const temporaryController = streamControllers.get(null);
        temporaryController?.abort();
        streamControllers.delete(null);
        const temporaryLive = liveStreams.get(null);
        releaseLiveBubbleTimers(temporaryLive?.dom?.assistantBubble || null);
        deleteLiveStreamKey(null, temporaryController);
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
                    <svg width="26" height="26" viewBox="0 0 32 32" aria-hidden="true">
                        <path fill-rule="evenodd" fill="currentColor"
                              d="M9.5 3h13A6.5 6.5 0 0 1 29 9.5v13a6.5 6.5 0 0 1-6.5 6.5h-13A6.5 6.5 0 0 1 3 22.5v-13A6.5 6.5 0 0 1 9.5 3zM10 9.5h4.2v9h7.3v4.2H10z"/>
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

    if (temporaryChatEnabled) {
        const temporaryLive = liveStreams.get(null);
        if (temporaryLive && !temporaryLive.done) {
            chatMessages.querySelector(".chatgpt-welcome-hero")?.remove();
            renderLiveSessionFromStore(temporaryLive);
        }
    }

    await loadSessions();
}

async function deleteSession(sessionId) {
    try {
        const controller = streamControllers.get(sessionId);
        if (controller) controller.abort();
        streamControllers.delete(sessionId);
        deleteLiveStreamKey(sessionId, controller);
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

