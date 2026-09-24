(function (root, factory) {
    const api = factory(root);
    if (typeof module === "object" && module.exports) {
        module.exports = api;
    }
    if (root) {
        root.LasmeAnswerStream = api;
    }
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
    "use strict";

    // content_reset : le texte streamé n'était PAS la réponse finale
    // (brouillon avant appels d'outils, réponse écartée par le harnais,
    // tour relancé après dépassement de budget). Garantie d'UX : ce texte
    // n'est JAMAIS supprimé de l'écran — il se range en note de travail
    // dépliable, et seule la réponse finale occupe la zone de réponse.
    const REASON_LABELS = {
        tool_call: "Brouillon avant vérification",
        fetch_required_before_answer: "Brouillon non vérifié",
        search_required_by_request: "Brouillon non vérifié",
        budget_retried: "Brouillon interrompu, réécrit",
        harness_rejected: "Brouillon écarté",
    };

    function reasonLabel(reason) {
        return REASON_LABELS[reason] || "Brouillon de travail";
    }

    function countWords(text) {
        const trimmed = String(text || "").trim();
        return trimmed ? trimmed.split(/\s+/).length : 0;
    }

    function workNoteTitle(reason, text) {
        const words = countWords(text);
        return (
            "✎ "
            + reasonLabel(reason)
            + " · "
            + words
            + " mot"
            + (words > 1 ? "s" : "")
        );
    }

    function workNotePreview(text, limit) {
        const max = Number.isFinite(limit) ? limit : 160;
        const flat = String(text || "").replace(/\s+/g, " ").trim();
        return flat.length > max ? `${flat.slice(0, max - 1)}…` : flat;
    }

    // Les notes vivent dans leur propre nœud persistant : elles ne doivent
    // JAMAIS être dans .answer-content, dont innerHTML est réécrit à chaque
    // peinture du renderer progressif (comme les cartes d'outils).
    function ensureWorkNotesGroup(container) {
        let group = container.querySelector(":scope > .work-notes-group");
        if (group) return group;
        group = document.createElement("div");
        group.className = "work-notes-group";
        const thinking = container.querySelector(":scope > .thinking-panel");
        const tools = container.querySelector(":scope > .agent-tools-group");
        const answer = container.querySelector(":scope > .answer-content");
        if (thinking) {
            thinking.after(group);
        } else if (tools) {
            tools.after(group);
        } else if (answer) {
            answer.before(group);
        } else {
            container.appendChild(group);
        }
        return group;
    }

    function foldIntoWorkNote(container, text, reason) {
        const value = String(text || "");
        const group = ensureWorkNotesGroup(container);
        const note = document.createElement("details");
        note.className = "work-note";
        note.title = workNotePreview(value);
        const summary = document.createElement("summary");
        summary.textContent = workNoteTitle(reason, value);
        const body = document.createElement("pre");
        body.className = "work-note-text";
        body.textContent = value;
        note.appendChild(summary);
        note.appendChild(body);
        group.appendChild(note);
        const answer = container.querySelector(":scope > .answer-content");
        if (answer) answer.remove();
        return note;
    }

    // Pendant la rédaction, le texte affiché est visiblement PROVISOIRE :
    // l'utilisateur ne peut pas le prendre pour la réponse finale.
    function setDrafting(container, on) {
        if (!container) return;
        container.classList.toggle("is-drafting", Boolean(on));
    }

    return {
        REASON_LABELS,
        reasonLabel,
        countWords,
        workNoteTitle,
        workNotePreview,
        ensureWorkNotesGroup,
        foldIntoWorkNote,
        setDrafting,
    };
});
