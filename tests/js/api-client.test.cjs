const test = require("node:test");
const assert = require("node:assert/strict");
const client = require("../../chat/web/src/api/client.js");

test("le découpage SSE isole les frames complètes et garde le reste", () => {
    const { events, rest } = client.splitSSE(
        'data: {"type":"content_delta","content":"Bonjour"}\n\n'
        + 'data: {"type":"content_replace","text":"Bonjour tout le monde"}\n'
    );
    assert.equal(events.length, 1);
    assert.equal(events[0].payload.type, "content_delta");
    assert.equal(events[0].payload.content, "Bonjour");
    assert.ok(rest.includes("content_replace"));
});

test("le marqueur [DONE] est remonté comme fin de flux", () => {
    const { events, rest } = client.splitSSE("data: [DONE]\n\n");
    assert.equal(events.length, 1);
    assert.equal(events[0].done, true);
    assert.equal(rest, "");
});

test("une frame non JSON n'est jamais perdue", () => {
    const { events } = client.splitSSE("data: pas-du-json\n\n");
    assert.equal(events[0].raw, "pas-du-json");
});

test("plusieurs frames d'un coup sont toutes remontées", () => {
    const buffer = [
        'data: {"type":"reasoning_start"}',
        "",
        'data: {"type":"reasoning_delta","text":"x"}',
        "",
        "data: [DONE]",
        "",
        "",
    ].join("\n");
    const { events } = client.splitSSE(buffer);
    assert.equal(events.length, 3);
    assert.equal(events[1].payload.text, "x");
    assert.equal(events[2].done, true);
});

test("les headers portent le token quand il existe", () => {
    global.sessionStorage = {
        getItem: () => "secret-token",
        setItem: () => {},
    };
    try {
        const headers = client.authHeaders({ "Content-Type": "application/json" });
        assert.equal(headers["X-Lasme-Token"], "secret-token");
        assert.equal(headers["Content-Type"], "application/json");
    } finally {
        delete global.sessionStorage;
    }
});

test("sans token, aucun header d'authentification n'est injecté", () => {
    const headers = client.authHeaders();
    assert.equal(headers["X-Lasme-Token"], undefined);
});
