from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock

from fastapi.testclient import TestClient

import chat.server.main as server_main
from core.artifacts.store import ArtifactStore
from core.config import settings
from core.memory.database import DatabaseManager


def _setup_isolated_stores(tmp_path: Path, monkeypatch):
    db_file = tmp_path / "features_suite.db"
    isolated_db = DatabaseManager(db_file)
    isolated_artifacts = ArtifactStore(db_file)
    monkeypatch.setattr(settings, "access_token", "test-secret-token-very-long-123")
    monkeypatch.setattr(server_main, "db", isolated_db, raising=False)
    monkeypatch.setattr(server_main, "artifact_store", isolated_artifacts, raising=False)
    server_main.deps.bind(db=isolated_db, artifact_store=isolated_artifacts)
    client = TestClient(
        server_main.app,
        headers={"X-Lasme-Token": "test-secret-token-very-long-123"},
    )
    return isolated_db, isolated_artifacts, client


def test_feature1_pinned_sessions_and_fts5_search(tmp_path: Path, monkeypatch):
    isolated_db, isolated_artifacts, client = _setup_isolated_stores(tmp_path, monkeypatch)

    s1 = isolated_db.create_session("Première session", project_id="default")
    s2 = isolated_db.create_session("Architecture souveraine", project_id="default")
    isolated_db.add_message(
        s2["id"],
        "assistant",
        "Le moteur utilise SQLite FTS5 et llama-server sur RTX 4070 Ti SUPER.",
    )
    isolated_artifacts.create(
        project_id="default",
        title="Note FTS5",
        content="Documentation sur la recherche plein texte FTS5.",
        kind="markdown",
    )

    # Pin s2 and verify ordering puts pinned session first
    pin_resp = client.put(
        f"/api/sessions/{s2['id']}",
        json={"pinned": True},
    )
    assert pin_resp.status_code == 200
    assert pin_resp.json()["session"]["pinned"] is True

    list_resp = client.get("/api/sessions?project_id=default")
    assert list_resp.status_code == 200
    sessions = list_resp.json()["sessions"]
    assert sessions[0]["id"] == s2["id"]
    assert sessions[0]["pinned"] is True
    assert sessions[1]["id"] == s1["id"]

    # Search via FTS5 endpoint
    search_resp = client.get("/api/sessions/search?q=FTS5&project_id=default")
    assert search_resp.status_code == 200
    payload = search_resp.json()
    assert len(payload["messages"]) >= 1
    assert payload["messages"][0]["session_id"] == s2["id"]
    assert "FTS5" in payload["messages"][0]["snippet"]
    assert len(payload["artifacts"]) == 1
    assert payload["artifacts"][0]["title"] == "Note FTS5"


def test_feature3_session_export_and_import(tmp_path: Path, monkeypatch):
    isolated_db, _, client = _setup_isolated_stores(tmp_path, monkeypatch)

    sess = isolated_db.create_session("Audit Financier", project_id="default")
    isolated_db.add_message(sess["id"], "user", "Analyse le bilan 2026.")
    isolated_db.add_message(
        sess["id"],
        "assistant",
        "Voici la synthèse avec marge nette de 18 %.",
        metadata={"sources": [{"title": "Rapport Annuel", "url": "https://example.com/bilan"}]},
    )

    # Export HTML, Markdown, PDF, and JSON
    for fmt, expected_mime in [
        ("html", "text/html"),
        ("md", "text/markdown"),
        ("pdf", "application/pdf"),
        ("json", "application/json"),
    ]:
        resp = client.get(f"/api/sessions/{sess['id']}/export?format={fmt}")
        assert resp.status_code == 200
        assert expected_mime in resp.headers.get("content-type", "")
        assert len(resp.content) > 20

    # Re-import JSON bundle
    json_resp = client.get(f"/api/sessions/{sess['id']}/export?format=json")
    bundle = json.loads(json_resp.text)
    import_resp = client.post(
        "/api/sessions/import",
        json={"bundle": bundle, "project_id": "default"},
    )
    assert import_resp.status_code == 200
    imported_data = import_resp.json()
    assert imported_data["imported_messages"] == 2
    assert imported_data["session"]["id"] != sess["id"]


def test_feature4_chat_compare_duel_endpoint(tmp_path: Path, monkeypatch):
    _, _, client = _setup_isolated_stores(tmp_path, monkeypatch)
    fake_client = AsyncMock()
    fake_client.chat = AsyncMock(
        side_effect=[
            {
                "message": {"content": "Réponse rapide E4B."},
                "eval_count": 12,
            },
            {
                "message": {
                    "content": "Réponse approfondie 12B.",
                    "thinking": "Analyse préalable.",
                },
                "eval_count": 28,
            },
        ]
    )
    monkeypatch.setattr(server_main, "client", fake_client, raising=False)
    server_main.deps.bind(client=fake_client)

    resp = client.post(
        "/api/chat/compare",
        json={
            "prompt": "Compare les architectures RAG et CAG.",
            "left": {"model": "gemma-4-e4b", "effort": "low"},
            "right": {"model": "gemma-4-12b", "effort": "high"},
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["left"]["model"] == "gemma-4-e4b"
    assert "Réponse rapide E4B" in data["left"]["content"]
    assert data["right"]["model"] == "gemma-4-12b"
    assert "Réponse approfondie 12B" in data["right"]["content"]
    assert data["right"]["output_tokens"] == 28


def test_feature5_media_transcribe_endpoint(tmp_path: Path, monkeypatch):
    _, _, client = _setup_isolated_stores(tmp_path, monkeypatch)

    resp = client.post(
        "/api/media/transcribe",
        json={"language": "fr-FR", "text_hint": "Bonjour Lasme, résume mes notes."},
    )
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["status"] == "ok"
    assert payload["text"] == "Bonjour Lasme, résume mes notes."


def test_feature6_scheduled_missions_crud_and_run(tmp_path: Path, monkeypatch):
    _, _, client = _setup_isolated_stores(tmp_path, monkeypatch)
    fake_client = AsyncMock()
    fake_client.chat = AsyncMock(
        return_value={
            "message": {
                "content": "# Briefing IA\n\n- **Point 1** : Avancées GGUF.\n- **Point 2** : Gains VRAM."
            }
        }
    )
    monkeypatch.setattr(server_main, "client", fake_client, raising=False)
    server_main.deps.bind(client=fake_client)

    create_resp = client.post(
        "/api/missions",
        json={
            "title": "Veille Quotidienne IA",
            "prompt": "Résume les nouveautés llama.cpp et Gemma 4.",
            "project_id": "default",
            "model": "gemma-4-12b",
            "schedule_label": "Quotidien · 08:00",
            "interval_minutes": 1440,
            "enabled": True,
        },
    )
    assert create_resp.status_code == 200
    mission = create_resp.json()["mission"]
    mission_id = mission["id"]

    # Run mission immediately
    run_resp = client.post(f"/api/missions/{mission_id}/run")
    assert run_resp.status_code == 200
    run_data = run_resp.json()
    assert run_data["mission"]["last_status"] == "success"
    assert run_data["artifact"]["kind"] == "research"
    assert "Briefing IA" in run_data["artifact"]["content"]

    # Delete mission
    del_resp = client.delete(f"/api/missions/{mission_id}")
    assert del_resp.status_code == 200
    assert client.get("/api/missions").json()["missions"] == []
