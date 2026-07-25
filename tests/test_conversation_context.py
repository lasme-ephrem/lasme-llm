import unittest
import tempfile
from pathlib import Path

from chat.server.main import (
    ChatMessage,
    _fallback_contextual_search_query,
    clean_model_text,
    is_simple_factual_lookup,
    should_enable_reasoning,
    should_perform_web_search,
)
from core.memory.context import select_conversation_context
from core.memory.database import DatabaseManager


class ConversationContextTests(unittest.TestCase):
    def test_follow_up_keeps_previous_topic(self):
        messages = [
            ChatMessage(
                role="user",
                content="Qui est le dernier vainqueur de la coupe du monde ?",
            ),
            ChatMessage(
                role="assistant",
                content="Le dernier vainqueur connu est l'Argentine.",
            ),
            ChatMessage(
                role="user",
                content="Et maintenant tu peux me donner la bonne réponse ?",
            ),
        ]

        query = _fallback_contextual_search_query(messages)

        self.assertIn("vainqueur de la coupe du monde", query.lower())
        self.assertIn("informations à jour", query.lower())

    def test_multi_turn_follow_up_keeps_root_topic(self):
        messages = [
            ChatMessage(role="user", content="Qui a gagné la Coupe du monde ?"),
            ChatMessage(role="assistant", content="L'Espagne [1]."),
            ChatMessage(role="user", content="Comment s'est passée la finale ?"),
            ChatMessage(role="assistant", content="Elle s'est terminée 1-0 [1]."),
            ChatMessage(role="user", content="Et le meilleur buteur ?"),
        ]

        query = _fallback_contextual_search_query(messages)

        self.assertIn("coupe du monde", query.lower())
        self.assertIn("meilleur buteur", query.lower())

    def test_feedback_triggers_search_when_conversation_has_context(self):
        self.assertTrue(
            should_perform_web_search(
                "C'est faux",
                user_toggle_enabled=True,
                has_conversation_context=True,
            )
        )

    def test_current_event_follow_up_inherits_web_search(self):
        messages = [
            ChatMessage(
                role="user",
                content="Qui est le vainqueur récent de la Coupe du monde ?",
            ),
            ChatMessage(
                role="assistant",
                content="L'Espagne a remporté la Coupe du monde 2026 [1].",
            ),
            ChatMessage(
                role="user",
                content="Comment s'est déroulé le match ?",
            ),
        ]
        self.assertTrue(
            should_perform_web_search(
                messages[-1].content,
                user_toggle_enabled=True,
                has_conversation_context=True,
                mode="auto",
                conversation_messages=messages,
            )
        )

    def test_generated_text_removes_foreign_script_and_mojibake(self):
        self.assertEqual(
            clean_model_text("privilégiant laសervation"),
            "privilégiant laervation",
        )
        self.assertEqual(clean_model_text("Lâ€™équipe"), "L’équipe")

    def test_greeting_never_triggers_search(self):
        self.assertFalse(
            should_perform_web_search(
                "Bonjour",
                user_toggle_enabled=True,
                has_conversation_context=True,
            )
        )

    def test_disabled_web_never_triggers_search(self):
        self.assertFalse(
            should_perform_web_search(
                "Qui a gagné la Coupe du monde ?",
                user_toggle_enabled=False,
                has_conversation_context=True,
            )
        )

    def test_reasoning_is_hidden_for_greeting_and_enabled_for_complex_task(self):
        self.assertFalse(
            should_enable_reasoning(
                "Bonjour",
                model="gemma-4-chat",
                requested_level="balanced",
            )
        )
        self.assertTrue(
            should_enable_reasoning(
                "Analyse cette architecture et vérifie les risques principaux.",
                model="gemma-4-chat",
                requested_level="balanced",
            )
        )

    def test_external_context_enables_balanced_reasoning(self):
        self.assertEqual(
            should_enable_reasoning(
                "Résume les résultats",
                model="gemma-4-chat",
                requested_level="balanced",
                has_external_context=True,
            ),
            "medium",
        )

    def test_simple_web_fact_never_uses_slow_reasoning(self):
        query = "Qui est le dernier vainqueur de la Coupe du monde ?"
        self.assertTrue(is_simple_factual_lookup(query))
        self.assertFalse(
            should_enable_reasoning(
                query,
                model="gemma-4-fable",
                requested_level="balanced",
                has_external_context=True,
            )
        )

    def test_reasoning_levels_map_to_ollama_effort(self):
        self.assertFalse(
            should_enable_reasoning(
                "Analyse cette architecture",
                model="gemma-4-fable",
                requested_level="fast",
            )
        )
        self.assertEqual(
            should_enable_reasoning(
                "Analyse cette architecture",
                model="gemma-4-fable",
                requested_level="high",
            ),
            "high",
        )
        self.assertEqual(
            should_enable_reasoning(
                "Analyse cette architecture",
                model="gemma-4-fable",
                requested_level="max",
            ),
            "max",
        )

    def test_auto_web_search_skips_stable_question(self):
        self.assertFalse(
            should_perform_web_search(
                "Explique le théorème de Pythagore",
                user_toggle_enabled=True,
                mode="auto",
            )
        )
        self.assertTrue(
            should_perform_web_search(
                "Quelle est la dernière version disponible ?",
                user_toggle_enabled=True,
                mode="auto",
            )
        )
        self.assertTrue(
            should_perform_web_search(
                "Qui est le vainqueur de la Coupe du monde ?",
                user_toggle_enabled=True,
                mode="auto",
            )
        )

    def test_context_keeps_recent_relevant_and_durable_memory(self):
        messages = [
            {
                "role": "user" if index % 2 == 0 else "assistant",
                "content": (
                    "Je veux utiliser Ollama uniquement avec des modèles GGUF."
                    if index == 0
                    else f"Échange secondaire numéro {index} sur un autre sujet."
                ),
            }
            for index in range(16)
        ]
        messages.append(
            {
                "role": "user",
                "content": "Et pour Ollama, rappelle-moi ce que j'avais décidé ?",
            }
        )

        selection = select_conversation_context(
            messages,
            latest_query=messages[-1]["content"],
            summary="L'utilisateur préfère des réponses concises.",
            max_history_tokens=900,
            recent_message_limit=4,
            relevant_message_limit=2,
        )

        contents = "\n".join(str(item["content"]) for item in selection.messages)
        self.assertTrue(selection.summary_used)
        self.assertEqual(selection.messages[0]["role"], "system")
        self.assertIn("modèles GGUF", contents)
        self.assertIn("rappelle-moi", contents)
        self.assertLessEqual(selection.estimated_tokens, 900)

    def test_database_persists_compacted_memory(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = DatabaseManager(Path(temp_dir) / "memory-test.db")
            session = manager.create_session(model="gemma-4-chat:latest")
            manager.update_session_memory(
                session["id"],
                "L'utilisateur préfère les modèles GGUF.",
                12,
            )

            memory = manager.get_session_memory(session["id"])

            self.assertEqual(memory["summary_message_count"], 12)
            self.assertIn("GGUF", memory["summary"])


if __name__ == "__main__":
    unittest.main()
