import unittest
import tempfile
from pathlib import Path

from chat.server.main import (
    ChatMessage,
    _fallback_contextual_search_query,
    clean_model_text,
    iter_stream_text_chunks,
    is_simple_factual_lookup,
    provider_answer_is_usable,
    response_presentation_profile,
    response_depth_instruction,
    should_enable_reasoning,
    should_perform_web_search,
    strip_web_citation_markers,
    unsupported_grounded_numbers,
    can_reuse_previous_web_context,
)
from core.tools.search_ranking import requires_strict_grounding
from core.memory.context import select_conversation_context
from core.memory.database import DatabaseManager


class ConversationContextTests(unittest.TestCase):
    def test_previous_web_context_is_only_reused_for_a_real_follow_up(self):
        self.assertTrue(
            can_reuse_previous_web_context(
                "Est-ce que je pourrai le faire tourner en local ?"
            )
        )
        self.assertTrue(
            can_reuse_previous_web_context("Et quelles sont ses limites ?")
        )
        self.assertFalse(
            can_reuse_previous_web_context(
                "Quelles sont les dernières nouvelles dans le monde de l'IA ?"
            )
        )

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
        self.assertEqual(
            clean_model_text("La fonction θ vérifie ∑ xᵢ = μ."),
            "La fonction θ vérifie ∑ xᵢ = μ.",
        )

    def test_completed_provider_answer_is_split_without_data_loss(self):
        answer = (
            "Voici un premier fait vérifié. "
            "Voici un deuxième fait avec une citation [1]. "
        ) * 8
        chunks = list(iter_stream_text_chunks(answer, target_chars=48))

        self.assertGreater(len(chunks), 4)
        self.assertEqual("".join(chunks), answer)
        self.assertTrue(all(chunks))

    def test_greeting_never_triggers_search(self):
        self.assertFalse(
            should_perform_web_search(
                "Bonjour",
                user_toggle_enabled=True,
                has_conversation_context=True,
            )
        )
        messages = [
            ChatMessage(
                role="user",
                content="Quelles sont les dernières nouvelles dans l'IA ?",
            ),
            ChatMessage(
                role="assistant",
                content="Voici cinq actualités récentes [1][2].",
            ),
            ChatMessage(role="user", content="Bonjour, comment tu vas ?"),
        ]
        self.assertFalse(
            should_perform_web_search(
                messages[-1].content,
                user_toggle_enabled=True,
                has_conversation_context=True,
                mode="auto",
                conversation_messages=messages,
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

    def test_auto_web_search_recognizes_recent_ai_model_names(self):
        self.assertTrue(
            should_perform_web_search(
                "Tu connais Kimi K3 ?",
                user_toggle_enabled=True,
                mode="auto",
            )
        )
        self.assertTrue(
            should_perform_web_search(
                "Est-ce que je pourrai le faire tourner en local ?",
                user_toggle_enabled=True,
                has_conversation_context=True,
                mode="auto",
                has_prior_web_evidence=True,
            )
        )

    def test_cost_comparisons_require_strict_web_grounding(self):
        query = (
            "Produit un tableau comparatif des modèles LLM chinois "
            "avec leurs coûts"
        )
        self.assertTrue(requires_strict_grounding(query))
        self.assertTrue(
            should_perform_web_search(
                query,
                user_toggle_enabled=True,
                mode="auto",
            )
        )
        self.assertEqual(response_presentation_profile(query)[0], "comparison")
        self.assertIn(
            "longueur moyenne",
            response_depth_instruction(query, "balanced"),
        )

    def test_unsupported_price_claims_are_detected(self):
        evidence = "Le tarif vérifié est de $0.27 en entrée et $1.10 en sortie."
        self.assertEqual(
            unsupported_grounded_numbers(
                "Le tarif est de $0.27 en entrée et $1.10 en sortie.",
                evidence,
            ),
            [],
        )
        self.assertEqual(
            unsupported_grounded_numbers(
                "Le tarif est de $0.27 en entrée et $30 en sortie.",
                evidence,
            ),
            ["$30"],
        )

    def test_comparison_refinement_keeps_the_root_topic(self):
        messages = [
            ChatMessage(
                role="user",
                content=(
                    "Compare DeepSeek, Kimi, les modèles de OpenAI, "
                    "Google et Anthropic"
                ),
            ),
            ChatMessage(role="assistant", content="Comparatif initial."),
            ChatMessage(
                role="user",
                content=(
                    "Concentre-toi maintenant sur les performances "
                    "techniques et les tarifs API."
                ),
            ),
        ]
        query = _fallback_contextual_search_query(messages)
        self.assertIn("DeepSeek", query)
        self.assertIn("Anthropic", query)
        self.assertIn("tarifs API", query)

    def test_web_citations_are_removed_without_touching_code(self):
        value = (
            "Les poids sont publics [9][11] [Source 5] (Source 8). "
            "`values = [1, 2]`\n"
            "```python\nitems = [1, 2, 3]\n```"
        )
        self.assertEqual(
            strip_web_citation_markers(value),
            (
                "Les poids sont publics. "
                "`values = [1, 2]`\n"
                "```python\nitems = [1, 2, 3]\n```"
            ),
        )

    def test_provider_cannot_deny_web_access_when_sources_exist(self):
        results = [
            {
                "title": "Kimi K3",
                "url": "https://huggingface.co/moonshotai/Kimi-K3",
            }
        ]
        self.assertFalse(
            provider_answer_is_usable(
                "Je ne peux pas me connecter à Internet en temps réel.",
                results,
                ["huggingface.co"],
            )
        )
        self.assertTrue(
            provider_answer_is_usable(
                "Kimi K3 est publié avec ses poids ouverts.",
                results,
                ["huggingface.co"],
            )
        )

    def test_project_document_request_does_not_inherit_old_web_context(self):
        messages = [
            ChatMessage(
                role="user",
                content="Quelle est la date de livraison en 2026 ?",
            ),
            ChatMessage(
                role="assistant",
                content="La livraison est prÃ©vue en novembre 2026 [1].",
            ),
            ChatMessage(
                role="user",
                content="Fais un rapport des fichiers dans ce projet.",
            ),
        ]

        self.assertFalse(
            should_perform_web_search(
                messages[-1].content,
                user_toggle_enabled=True,
                has_conversation_context=True,
                mode="auto",
                conversation_messages=messages,
            )
        )
        self.assertFalse(
            should_perform_web_search(
                "Explique ce document de A Ã  Z.",
                user_toggle_enabled=True,
                has_conversation_context=True,
                mode="auto",
                conversation_messages=messages,
            )
        )

    def test_recent_sports_follow_ups_always_use_web(self):
        messages = [
            ChatMessage(
                role="user",
                content="Lionel Messi nombre de buts total en Coupe du monde",
            ),
            ChatMessage(
                role="assistant",
                content="Il a inscrit 13 buts jusqu'en 2022.",
            ),
            ChatMessage(
                role="user",
                content="Combien de buts a-t-il marqué en 2026 ?",
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
        query = _fallback_contextual_search_query(messages)
        self.assertIn("lionel messi", query.lower())
        self.assertIn("2026", query)

    def test_sports_statistics_trigger_web_without_repeating_competition(self):
        self.assertTrue(
            should_perform_web_search(
                "Quel est son bilan actuel ?",
                user_toggle_enabled=True,
                has_conversation_context=True,
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
        self.assertTrue(
            should_perform_web_search(
                "Qui a remporté la Coupe du monde de football 2026 ?",
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
