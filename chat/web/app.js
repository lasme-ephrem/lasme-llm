"use strict";
// app.js — noyau d'état partagé (découpage modulaire, ROADMAP C1).
// Tout le reste vit dans chat/web/src/**, chargé APRÈS ce fichier.
let API_BASE = "/api";
const LASME_FAST_MODEL = "lasme-smol-fast";
const LASME_REASONING_MODEL = "gemma-4-e4b"; // génération de prompts image (profil rapide)

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

