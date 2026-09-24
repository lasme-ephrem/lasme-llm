const test = require("node:test");
const assert = require("node:assert/strict");
const answerStream = require("../../chat/web/answer-stream.js");

test("chaque raison de retrait a un libellé explicite, avec repli", () => {
    assert.equal(
        answerStream.reasonLabel("tool_call"),
        "Brouillon avant vérification"
    );
    assert.equal(
        answerStream.reasonLabel("fetch_required_before_answer"),
        "Brouillon non vérifié"
    );
    assert.equal(
        answerStream.reasonLabel("budget_retried"),
        "Brouillon interrompu, réécrit"
    );
    assert.equal(
        answerStream.reasonLabel("inconnu"),
        "Brouillon de travail"
    );
});

test("le titre de note compte les mots et gère le pluriel", () => {
    assert.equal(
        answerStream.workNoteTitle("tool_call", "un deux trois"),
        "✎ Brouillon avant vérification · 3 mots"
    );
    assert.equal(
        answerStream.workNoteTitle("tool_call", "seul"),
        "✎ Brouillon avant vérification · 1 mot"
    );
    assert.equal(
        answerStream.workNoteTitle("tool_call", "   "),
        "✎ Brouillon avant vérification · 0 mot"
    );
});

test("l'aperçu de note est borné, sur une ligne, sans tronquer abruptement", () => {
    const preview = answerStream.workNotePreview(`a\n\nb ${"x".repeat(300)}`);
    assert.ok(preview.length <= 160);
    assert.ok(!preview.includes("\n"));
    assert.ok(preview.endsWith("…"));
    assert.equal(answerStream.workNotePreview("court"), "court");
});

test("le rangement expose une API DOM stable (contrat)", () => {
    assert.equal(typeof answerStream.foldIntoWorkNote, "function");
    assert.equal(typeof answerStream.setDrafting, "function");
    assert.equal(typeof answerStream.ensureWorkNotesGroup, "function");
});
