const test = require("node:test");
const assert = require("node:assert/strict");
const progressive = require("../../chat/web/progressive-renderer.js");

test("reveals a large provider response over several frames", () => {
    const targetLength = 2400;
    let currentLength = 0;
    let frameCount = 0;

    while (currentLength < targetLength && frameCount < 200) {
        const nextLength = progressive.nextVisibleLength(
            currentLength,
            targetLength
        );
        assert.ok(nextLength > currentLength);
        assert.ok(nextLength <= targetLength);
        currentLength = nextLength;
        frameCount += 1;
    }

    assert.equal(currentLength, targetLength);
    assert.ok(frameCount > 5);
    assert.ok(frameCount < 100);
});

test("small local-model deltas remain immediately visible", () => {
    assert.equal(progressive.nextVisibleLength(20, 24), 24);
    assert.equal(progressive.nextVisibleLength(0, 1), 1);
});

test("removes raw Web citation markers from prose", () => {
    assert.equal(
        progressive.stripNumericCitations(
            "Les poids sont publics [9][11], donc le modèle peut être téléchargé [1]."
        ),
        "Les poids sont publics, donc le modèle peut être téléchargé."
    );
});

test("preserves numeric arrays inside inline and fenced code", () => {
    const value = [
        "Exemple `scores = [1, 2]` [3].",
        "```python",
        "values = [1, 2, 3]",
        "```",
    ].join("\n");
    assert.equal(
        progressive.stripNumericCitations(value),
        [
            "Exemple `scores = [1, 2]`.",
            "```python",
            "values = [1, 2, 3]",
            "```",
        ].join("\n")
    );
});

test("la révélation continue dans un onglet masqué (requestAnimationFrame gelé)", async () => {
    const frozenFrames = [];
    const originalRaf = globalThis.requestAnimationFrame;
    const originalDocument = globalThis.document;
    // Simule un onglet masqué : rAF présent mais JAMAIS déclenché.
    globalThis.requestAnimationFrame = (callback) => {
        frozenFrames.push(callback);
        return frozenFrames.length;
    };
    globalThis.document = { hidden: true };
    try {
        const container = { onglet: "masque" };
        let shown = "";
        await new Promise((resolve) => {
            const guard = setTimeout(resolve, 3000);
            progressive.schedule(
                container,
                "x".repeat(500),
                (_container, text) => {
                    shown = text;
                },
                {
                    final: true,
                    onComplete: () => {
                        clearTimeout(guard);
                        resolve();
                    },
                }
            );
        });
        assert.equal(shown, "x".repeat(500));
        assert.equal(frozenFrames.length, 0);
        progressive.cancel(container);
    } finally {
        if (originalRaf === undefined) delete globalThis.requestAnimationFrame;
        else globalThis.requestAnimationFrame = originalRaf;
        if (originalDocument === undefined) delete globalThis.document;
        else globalThis.document = originalDocument;
    }
});

test("la révélation se termine si l'onglet devient masqué APRÈS l'armement", async () => {
    // Cas réel : une frame armée onglet visible ne se déclenche jamais une
    // fois l'onglet masqué → le texte restait figé en plein milieu (199
    // caractères affichés pendant que la réponse complète était écrite en
    // base). Le filet de sécurité doit terminer le rendu malgré tout.
    const frozenFrames = [];
    const originalRaf = globalThis.requestAnimationFrame;
    const originalDocument = globalThis.document;
    let hidden = false;
    globalThis.requestAnimationFrame = (callback) => {
        frozenFrames.push(callback);
        return frozenFrames.length;
    };
    globalThis.document = {
        get hidden() {
            return hidden;
        },
    };
    try {
        const container = { onglet: "bascule" };
        const shown = [];
        progressive.schedule(container, "y".repeat(700), (_container, text) => {
            shown.push(text);
        });
        // L'onglet bascule juste après l'armement de la frame.
        hidden = true;
        const deadline = Date.now() + 3000;
        while (
            shown[shown.length - 1] !== "y".repeat(700)
            && Date.now() < deadline
        ) {
            await new Promise((resolve) => setTimeout(resolve, 50));
        }
        assert.ok(frozenFrames.length > 0, "une frame a bien été armée");
        assert.ok(shown.length > 1, "le rendu ne doit pas rester figé");
        assert.equal(
            shown[shown.length - 1],
            "y".repeat(700),
            "le texte complet doit finir par s'afficher"
        );
        progressive.cancel(container);
    } finally {
        if (originalRaf === undefined) delete globalThis.requestAnimationFrame;
        else globalThis.requestAnimationFrame = originalRaf;
        if (originalDocument === undefined) delete globalThis.document;
        else globalThis.document = originalDocument;
    }
});

test("une correction serveur s'affiche d'un bloc, sans être retapée", () => {
    const container = { correction: true };
    const paints = [];
    progressive.schedule(container, "Version brouillon de la réponse.", (_c, text) => {
        paints.push(text);
    });
    paints.length = 0;
    progressive.schedule(
        container,
        "Version corrigée et complète de la réponse.",
        (_c, text) => {
            paints.push(text);
        },
        { replace: true }
    );
    assert.deepEqual(paints, ["Version corrigée et complète de la réponse."]);
    progressive.cancel(container);
});

test("la fin de flux affiche la réponse entière même si les minuteurs sont étranglés", async () => {
    // Cas réel : onglet masqué → les minuteurs sont étranglés (1/s, puis
    // 1/min) et la révélation progressive n'atteint jamais la fin. La
    // réponse restait tronquée à l'écran alors qu'elle était complète en
    // base (199 caractères affichés pour 700 écrits).
    const originalRaf = globalThis.requestAnimationFrame;
    const originalDocument = globalThis.document;
    let timerCalls = 0;
    const realSetTimeout = globalThis.setTimeout;
    globalThis.requestAnimationFrame = () => 0; // jamais déclenché
    globalThis.document = { hidden: true };
    globalThis.setTimeout = (callback, delay) => {
        timerCalls += 1;
        if (timerCalls > 3) {
            // Simule l'étranglement : la minuterie ne se déclenche plus.
            return 0;
        }
        return realSetTimeout(callback, delay);
    };
    try {
        const container = { onglet: "etrangle" };
        const shown = [];
        const answer = "Réponse complète et définitive.".repeat(20);
        progressive.schedule(container, answer, (_c, text) => {
            shown.push(text);
        });
        progressive.schedule(
            container,
            answer,
            (_c, text) => {
                shown.push(text);
            },
            { final: true }
        );
        assert.equal(
            shown[shown.length - 1],
            answer,
            "la fin de flux doit peindre le texte entier immédiatement"
        );
        progressive.cancel(container);
    } finally {
        globalThis.setTimeout = realSetTimeout;
        if (originalRaf === undefined) delete globalThis.requestAnimationFrame;
        else globalThis.requestAnimationFrame = originalRaf;
        if (originalDocument === undefined) delete globalThis.document;
        else globalThis.document = originalDocument;
    }
});
