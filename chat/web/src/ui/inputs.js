// Extrait verbatim de app.js (découpage modulaire — voir ROADMAP.md, C1).
// Script classique : les déclarations de top-level restent globales.
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
