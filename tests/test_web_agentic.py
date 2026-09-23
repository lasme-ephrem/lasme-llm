"""Phases W : recherche web agentique sans fournisseur synthétique."""

import unittest
from unittest.mock import patch

from core.agent.tools_web import (
    _format_search_results,
    collect_known_urls,
    strip_unsupported_citations,
)


def _fake_search_fn(query, max_results=None, messages=None, **kwargs):
    _fake_search_fn.last_kwargs = kwargs
    _fake_search_fn.last_query = query
    return {
        "status": "ok",
        "engine": "chain",
        "results": [
            {"title": "Resultat", "url": "https://exemple.fr/a", "snippet": "extrait"}
        ],
        "errors": [],
    }
_fake_search_fn.last_kwargs = {}


class WebSearchAgenticTests(unittest.IsolatedAsyncioTestCase):
    async def test_search_skips_sonar_and_strips_provider_answer(self):
        from core.agent.tools_web import _run_web_search

        _fake_search_fn.last_kwargs = {}
        output = await _run_web_search(
            _fake_search_fn, {"query": "prix rtx 5090", "recency": "day"}
        )
        self.assertTrue(
            _fake_search_fn.last_kwargs.get("skip_primary_provider") is True,
            "l'agent ne doit jamais appeler Perplexity Sonar",
        )
        self.assertIn("https://exemple.fr/a", output)
        self.assertNotIn("Moteur :", output)

    async def test_no_provider_answer_in_output(self):
        payload = {
            "results": [{"title": "t", "url": "https://a.fr", "snippet": "s"}],
            "provider_answer": "reponse pre-rédigée par un fournisseur",
        }
        text = _format_search_results(payload)
        self.assertNotIn("pré-rédigée", text)


class CitationGuardrailTests(unittest.TestCase):
    def test_collect_known_urls_from_events(self):
        events = [
            {"type": "turn_start", "turn": 1},
            {
                "type": "tool_call",
                "name": "fetch_pages",
                "arguments": '{"urls": ["https://lu.fr/page"]}',
            },
            {
                "type": "tool_result",
                "name": "web_search",
                "ok": True,
                "output": "[1] Titre\n    https://resultat.fr/a\n    ex",
            },
        ]
        known = collect_known_urls(events)
        self.assertIn("https://lu.fr/page", known)
        self.assertIn("https://resultat.fr/a", known)

    def test_strip_unsupported_citations(self):
        known = {"https://lu.fr/page"}
        text = (
            "Vu sur [ce site](https://lu.fr/page) et sur "
            "[celui-ci](https://hallucine.fr/x), plus https://invente.fr/a."
        )
        cleaned = strip_unsupported_citations(text, known)
        self.assertIn("(https://lu.fr/page)", cleaned)
        self.assertNotIn("hallucine.fr/x)", cleaned)
        self.assertIn("source non vérifiée retirée", cleaned)
        self.assertNotIn("invente.fr/a", cleaned)

    def test_keeps_supported_urls_intact(self):
        known = {"https://ok.fr"}
        text = "Source : https://ok.fr."
        self.assertEqual(strip_unsupported_citations(text, known), text)


