"""Garde-fou front ↔ serveur : chaque route /coding/ appelée doit exister.

Le front construit ses URLs en template string (`${API_BASE}/coding/...`) :
un simple grep sur « api/coding » ne les voit pas. Ce test liste les chemins
réellement enregistrés par FastAPI et refuse tout appel de route fantôme
(cas réel : les alias /coding/file-tree|file-content|save-file supprimés
alors que la section Studio du front les utilisait encore).
"""

import re
import unittest
from pathlib import Path

from chat.server.main import app

WEB_DIR = Path(__file__).resolve().parent.parent / "chat" / "web"
FRONT_CALL_RE = re.compile(r"\$\{API_BASE\}/coding/([a-z-]+(?:/[a-z-]+)*)")


def _served_paths(app):
    """Chemins réellement servis, routers inclus.

    Les routes sont enregistrées via include_router : selon la version de
    FastAPI, app.routes contient soit des Route (path direct), soit des
    enveloppes de router dont les routes vivent dans ``original_router``.
    """
    paths = set()
    for route in app.routes:
        path = getattr(route, "path", None)
        if path:
            paths.add(path)
            continue
        original = getattr(route, "original_router", None)
        for sub in getattr(original, "routes", None) or []:
            sub_path = getattr(sub, "path", None)
            if sub_path:
                paths.add(sub_path)
    return paths


class FrontCodingRoutesTests(unittest.TestCase):
    def test_frontend_only_calls_existing_coding_routes(self):
        served = _served_paths(app)
        referenced = set()
        # rglob : depuis le découpage C1, les appels vivent dans src/**.
        for js_file in sorted(WEB_DIR.rglob("*.js")):
            if "vendor" in js_file.parts:
                continue
            referenced.update(
                FRONT_CALL_RE.findall(js_file.read_text(encoding="utf-8"))
            )

        self.assertTrue(referenced, "aucun appel /coding/ trouvé dans le front")
        missing = {
            f"/api/coding/{name}" for name in referenced
        } - served
        self.assertEqual(
            missing,
            set(),
            f"routes /api/coding/ appelées par le front mais absentes : {sorted(missing)}",
        )


if __name__ == "__main__":
    unittest.main()
