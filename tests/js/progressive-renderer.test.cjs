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
