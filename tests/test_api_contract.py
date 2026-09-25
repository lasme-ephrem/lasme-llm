"""Contrats d'API : surface HTTP figée + conformité SSE (phases A2/A3).

- La surface des routes est figée dans ``tests/snapshots/api_routes.json`` :
  toute route supprimée (ou ajoutée) sans intention explicite fait échouer
  le test — c'est le filet anti-régression de la refacto modulaire.
- Tout événement SSE émis par les modules doit appartenir au contrat
  ``chat.contracts.sse_events`` (et tout ``content_reset`` à une raison
  déclarée).
"""

import json
import re
import unittest
from pathlib import Path

from chat.contracts.sse_events import EVENT_TYPES, RESET_REASONS
from chat.server.main import app

ROOT = Path(__file__).resolve().parent.parent
SNAPSHOT = ROOT / "tests" / "snapshots" / "api_routes.json"

_EVENT_LITERAL_RE = re.compile(r"['\"]type['\"]\s*:\s*['\"]([a-z_]+)['\"]")
_RESET_REASON_RE = re.compile(r"['\"]reason['\"]\s*:\s*['\"]([a-z_]+)['\"]")
_RESET_REASON_NOTE_RE = re.compile(r"['\"]reason['\"]\s*:\s*note\b")


def _route_rows(app):
    rows = set()
    for route in app.routes:
        methods = sorted(getattr(route, "methods", None) or [])
        path = getattr(route, "path", None)
        if path and methods:
            rows.update(f"{method} {path}" for method in methods)
        original = getattr(route, "original_router", None)
        for sub in getattr(original, "routes", None) or []:
            sub_methods = sorted(getattr(sub, "methods", None) or [])
            sub_path = getattr(sub, "path", None)
            if sub_path and sub_methods:
                rows.update(f"{method} {sub_path}" for method in sub_methods)
    return {
        row
        for row in rows
        if "/api/" in row or row.startswith(("GET /favicons", "POST /favicons"))
    }


def _emitted_event_types():
    types = set()
    for source in (ROOT / "chat" / "server").rglob("*.py"):
        for line in source.read_text(encoding="utf-8").splitlines():
            # Seules les frames réellement émises (json.dumps) comptent :
            # les dicts métier ("type": "directory"…) ne sont pas des SSE.
            if "json.dumps" in line or "data:" in line:
                types.update(_EVENT_LITERAL_RE.findall(line))
    return types


class ApiContractTests(unittest.TestCase):
    def test_api_surface_matches_snapshot(self):
        expected = set(json.loads(SNAPSHOT.read_text(encoding="utf-8")))
        served = _route_rows(app)
        self.assertEqual(
            sorted(expected - served),
            [],
            "routes supprimées sans mettre à jour le snapshot",
        )
        self.assertEqual(
            sorted(served - expected),
            [],
            "routes ajoutées sans mettre à jour le snapshot",
        )

    def test_every_emitted_sse_event_is_declared(self):
        emitted = _emitted_event_types()
        self.assertTrue(emitted, "aucun événement SSE détecté dans les modules")
        undeclared = emitted - EVENT_TYPES
        self.assertEqual(
            sorted(undeclared),
            [],
            "événements SSE émis hors contrat chat.contracts.sse_events",
        )

    def test_content_reset_reasons_are_declared(self):
        reasons = set()
        for source in (ROOT / "chat" / "server").rglob("*.py"):
            text = source.read_text(encoding="utf-8")
            for line in text.splitlines():
                if "json.dumps" in line or "data:" in line:
                    reasons.update(_RESET_REASON_RE.findall(line))
                if _RESET_REASON_NOTE_RE.search(line):
                    reasons |= RESET_REASONS
        undeclared = reasons - RESET_REASONS
        self.assertEqual(
            sorted(undeclared),
            [],
            "raisons de content_reset hors contrat",
        )


if __name__ == "__main__":
    unittest.main()
