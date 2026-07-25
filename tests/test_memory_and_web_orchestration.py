import tempfile
import unittest
from pathlib import Path

from core.memory.compaction import compactable_head, should_compact
from core.memory.database import DatabaseManager
from core.memory.personal import (
    format_personal_memory_context,
    is_safe_generated_memory,
)
from core.tools.specialized import detect_specialized_request
from core.tools.web_orchestrator import search_extract_verify


class PersonalMemoryTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db = DatabaseManager(Path(self.temp_dir.name) / "memory.db")

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_memory_is_editable_disableable_and_manual_items_are_preserved(self):
        manual = self.db.add_personal_memory(
            "Je préfère les réponses concises.",
            source="user",
        )
        self.db.update_personal_memory(manual["id"], enabled=False)
        self.db.replace_generated_memories(
            ["Le projet principal utilise Ollama.", "La langue préférée est le français."]
        )

        memories = self.db.list_personal_memories()
        manual_after = next(item for item in memories if item["id"] == manual["id"])
        self.assertFalse(manual_after["enabled"])
        self.assertEqual(
            len([item for item in memories if item["source"] == "generated"]),
            2,
        )

    def test_memory_context_only_contains_enabled_items(self):
        context = format_personal_memory_context(
            {"enabled": True},
            [
                {"content": "Répondre en français.", "enabled": True},
                {"content": "Ne pas utiliser ceci.", "enabled": False},
            ],
        )
        self.assertIn("Répondre en français", context)
        self.assertNotIn("Ne pas utiliser ceci", context)
        self.assertEqual(
            format_personal_memory_context({"enabled": False}, []),
            "",
        )

    def test_automatic_memory_rejects_likely_credentials(self):
        self.assertFalse(
            is_safe_generated_memory("Ma clé API est sk_examplevalue123456789")
        )
        self.assertTrue(
            is_safe_generated_memory("Je préfère recevoir les réponses en français.")
        )


class CompactionTests(unittest.TestCase):
    def test_old_external_payloads_are_removed_before_compaction(self):
        messages = [
            {
                "role": "user",
                "content": (
                    "Question durable\n"
                    "<document name=\"dump\">contenu externe massif</document>"
                ),
            },
            {"role": "assistant", "content": "Décision importante."},
        ] + [
            {"role": "user", "content": f"récent {index}"}
            for index in range(8)
        ]
        compacted = compactable_head(messages, 0, keep_recent=8)
        self.assertEqual(len(compacted["messages"]), 2)
        self.assertNotIn("contenu externe massif", compacted["messages"][0]["content"])

    def test_compaction_starts_after_many_unsummarized_turns(self):
        messages = [
            {"role": "user", "content": f"message {index}"}
            for index in range(14)
        ]
        self.assertTrue(should_compact(messages, 0, 50_000))


class WebOrchestrationTests(unittest.TestCase):
    def test_search_result_is_enriched_with_extracted_page_evidence(self):
        def fake_search(query, max_results):
            return {
                "status": "ok",
                "engine": "test",
                "errors": [],
                "results": [
                    {
                        "title": "Résultat officiel",
                        "url": "https://example.org/result",
                        "snippet": "Résumé initial concernant le vainqueur.",
                        "quality": "trusted",
                    }
                ],
                "strategy": {
                    "scope": "direct",
                    "official_domains": ["example.org"],
                    "candidate_count": 1,
                },
            }

        report = search_extract_verify(
            "dernier vainqueur officiel",
            search_fn=fake_search,
            fetch_fn=lambda url, timeout: (
                "La page officielle confirme le dernier vainqueur et la date de la finale."
            ),
        )
        self.assertEqual(report["strategy"]["extracted_count"], 1)
        self.assertEqual(report["strategy"]["verified_count"], 1)
        self.assertTrue(report["results"][0]["verified"])
        self.assertEqual(report["results"][0]["evidence_kind"], "page_extract")

    def test_provider_answer_keeps_citation_order_and_skips_extraction(self):
        def fake_search(query, max_results, conversation_messages=None):
            return {
                "status": "ok",
                "engine": "Perplexity Sonar",
                "answer_mode": "provider",
                "provider_answer": "Réponse vérifiée [1] puis [2].",
                "results": [
                    {"title": "Un", "url": "https://one.example", "snippet": "1"},
                    {"title": "Deux", "url": "https://two.example", "snippet": "2"},
                ],
                "strategy": {"scope": "direct"},
            }

        def forbidden_fetch(url, timeout):
            raise AssertionError("Provider-grounded answers must not be fetched again")

        report = search_extract_verify(
            "question actuelle",
            conversation_messages=[
                {"role": "user", "content": "question précédente"},
            ],
            search_fn=fake_search,
            fetch_fn=forbidden_fetch,
        )

        self.assertEqual(report["answer_mode"], "provider")
        self.assertEqual(report["strategy"]["verified_count"], 2)
        self.assertEqual(
            [item["title"] for item in report["results"]],
            ["Un", "Deux"],
        )

    def test_specialized_intent_detection_is_conservative(self):
        self.assertEqual(
            detect_specialized_request("Quelle est la météo à Paris ?")["type"],
            "weather",
        )
        self.assertEqual(
            detect_specialized_request("Quel est le cours du BTC ?")["type"],
            "crypto",
        )
        self.assertIsNone(detect_specialized_request("Explique-moi une closure Python"))


if __name__ == "__main__":
    unittest.main()
