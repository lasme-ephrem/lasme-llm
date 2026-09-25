(function (root, factory) {
    const api = factory(root);
    if (typeof module === "object" && module.exports) {
        module.exports = api;
    }
    if (root) {
        root.LasmeApiClient = api;
    }
})(typeof window !== "undefined" ? window : globalThis, function (global) {
    "use strict";

    // Client API unique (phase C2) : token, fetch JSON, découpage SSE.
    // Tous les appels du front doivent converger ici — c'est la couture
    // unique pour l'authentification, les erreurs HTTP et le protocole SSE
    // (contrat miroir de chat/contracts/sse_events.py côté serveur).
    const TOKEN_KEY = "lasme_access_token";

    function getToken() {
        try {
            return global.sessionStorage
                ? global.sessionStorage.getItem(TOKEN_KEY) || ""
                : "";
        } catch (_) {
            return "";
        }
    }

    function authHeaders(extra) {
        const headers = Object.assign({}, extra || {});
        const token = getToken();
        if (token && !headers["X-Lasme-Token"]) {
            headers["X-Lasme-Token"] = token;
        }
        return headers;
    }

    async function apiFetch(path, options) {
        const opts = Object.assign({}, options || {});
        opts.headers = authHeaders(opts.headers);
        const response = await global.fetch(path, opts);
        if (!response.ok) {
            let detail = `HTTP ${response.status}`;
            try {
                const payload = await response.json();
                detail = (payload && payload.detail) || detail;
            } catch (_) {}
            throw new Error(detail);
        }
        return response;
    }

    // Découpage d'un buffer SSE : frames complètes + reste non terminé.
    // Robuste aux coupures de chunk réseau (« data: …\n\n » partiel).
    function splitSSE(buffer) {
        const events = [];
        let rest = String(buffer || "");
        let index;
        while ((index = rest.indexOf("\n\n")) >= 0) {
            const frame = rest.slice(0, index);
            rest = rest.slice(index + 2);
            for (const line of frame.split("\n")) {
                const trimmed = line.trim();
                if (!trimmed.startsWith("data: ")) continue;
                const data = trimmed.slice(6).trim();
                if (data === "[DONE]") {
                    events.push({ done: true });
                    continue;
                }
                try {
                    events.push({ payload: JSON.parse(data) });
                } catch (_) {
                    events.push({ raw: data });
                }
            }
        }
        return { events, rest };
    }

    return {
        TOKEN_KEY,
        getToken,
        authHeaders,
        apiFetch,
        splitSSE,
    };
});
