import tempfile
import unittest
from pathlib import Path

from core.memory.compaction import compactable_head, should_compact
from core.memory.database import DatabaseManager
from core.memory.personal import (
    format_personal_memory_context,
    is_safe_generated_memory,
)


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

    def test_message_web_source_metadata_is_persisted(self):
        session = self.db.create_session()
        self.db.add_message(
            session["id"],
            "assistant",
            "Réponse sourcée [1].",
            metadata={
                "web_results": [
                    {
                        "title": "Source officielle",
                        "url": "https://example.org/source",
                        "engine": "test",
                    }
                ]
            },
        )

        messages = self.db.get_session_messages(session["id"])

        self.assertEqual(
            messages[0]["metadata"]["web_results"][0]["title"],
            "Source officielle",
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


if __name__ == "__main__":
    unittest.main()
