// Extrait verbatim de app.js (découpage modulaire — voir ROADMAP.md, C1).
// Script classique : les déclarations de top-level restent globales.
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

