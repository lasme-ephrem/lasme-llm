import unittest
import tempfile
from pathlib import Path

from chat.server.main import (
    ChatMessage,
    _fallback_contextual_search_query,
    clean_model_text,
    iter_stream_text_chunks,
    is_simple_factual_lookup,
    is_social_turn,
    response_presentation_profile,
    response_depth_instruction,
    should_enable_reasoning,
    strip_web_citation_markers,
    unsupported_grounded_numbers,
    ground_strict_answer,
    grounding_evidence_text,
)
from core.agent.grounding import requires_strict_grounding
from core.memory.context import select_conversation_context
from core.memory.database import DatabaseManager


class ConversationContextTests(unittest.TestCase):

    def test_contact_messages_are_social_and_real_requests_are_not(self):
        for message in (
            "bonjour",
            "Bonjour !",
            "Salut, comment ça va ?",
            "salut tout le monde",
            "hello there",
            "hey, tu es là ?",
            "coucou",
            "yo",
            "wesh",
            "cc",
            "bonjour à tous",
            "hey Lasme",
            "enchanté",
            "bonne soirée",
            "good morning",
            "merci beaucoup",
            "au revoir",
            "qui es-tu ?",
        ):
            self.assertTrue(is_social_turn(message), message)
        for message in (
            "Bonjour, quel est le cours du bitcoin ?",
            "salut, explique-moi la récursivité",
            "hello, cherche le prix de la RTX",
            "Combien font 6*7 ?",
        ):
            self.assertFalse(is_social_turn(message), message)

    def test_address_words_and_short_checkins_stay_social(self):
        for message in (
            "yo mon gars",
            "salut mon pote",
            "wesh frérot",
            "ping",
            "test",
            "yo gros",
        ):
            self.assertTrue(is_social_turn(message), message)
        for message in (
            "lance un test",
            "calcule mon total",
            "salut, quel est le cours du bitcoin ?",
        ):
            self.assertFalse(is_social_turn(message), message)

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

    def test_standard_effort_levels_pass_through(self):
        # Le niveau explicite de l'utilisateur est toujours respecté.
        for level, expected in (("low", "low"), ("medium", "medium"), ("high", "high")):
            self.assertEqual(
                should_enable_reasoning(
                    "Analyse cette architecture",
                    model="gemma-4-chat",
                    requested_level=level,
                ),
                expected,
            )
        # Même sur un tour trivial, un niveau explicite n'est pas abaissé.
        self.assertEqual(
            should_enable_reasoning("Bonjour", model="gemma-4-chat", requested_level="low"),
            "low",
        )

    def test_legacy_effort_labels_collapse_onto_high(self):
        self.assertEqual(
            should_enable_reasoning("Analyse", model="gemma-4-chat", requested_level="max"),
            "high",
        )
        self.assertEqual(
            should_enable_reasoning("Analyse", model="gemma-4-chat", requested_level="deep"),
            "high",
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
        # "max" est un héritage : il se replie sur "high" (échelle standard
        # low/medium/high) — voir test_legacy_effort_labels_collapse_onto_high.

    def test_cost_comparisons_require_strict_web_grounding(self):
        query = (
            "Produit un tableau comparatif des modèles LLM chinois "
            "avec leurs coûts"
        )
        self.assertTrue(requires_strict_grounding(query))
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

    def test_strict_grounding_uses_page_evidence_and_preserves_clarification(self):
        verified_page = "Le tarif actuellement publié est de 0,27 USD par million de jetons."
        answer = (
            "Le tarif est de 0,27 USD par million de jetons. "
            "Quel benchmark veux-tu comparer ?"
        )
        grounded = ground_strict_answer(answer, verified_page)
        self.assertIn("0,27 USD", grounded)
        self.assertIn("Quel benchmark", grounded)

        unsupported = ground_strict_answer(
            "Le tarif est de 30 USD. Quel benchmark veux-tu comparer ?",
            verified_page,
        )
        self.assertNotIn("30 USD", unsupported)
        self.assertIn("Quel benchmark", unsupported)

    def test_strict_grounding_never_replaces_the_whole_answer(self):
        """Sans preuve, la réponse est assagie — jamais remplacée en bloc.

        Régression réelle : la relance « et par rapport à Fable 5.1 ? »
        après une réponse sourcée a été remplacée par un refus administratif
        (« Je n'ai pas pu vérifier ce point… »). Le lecteur voyait sa
        réponse s'écrire puis disparaître.
        """
        answer = (
            "Opus 5.5 vise la parité de performance avec Fable 5.1 pour la\n"
            "*   **Coût** : environ 40 % moins cher que Opus 5.\n"
            "*   **Vitesse** : environ 30 % plus rapide que Opus 5.\n"
            "Le reste dépend de ton usage."
        )
        grounded = ground_strict_answer(answer, "")
        self.assertNotIn("Je n’ai pas pu vérifier", grounded)
        self.assertIn("Le reste dépend de ton usage.", grounded)
        self.assertIn("parité de performance avec Fable 5.1", grounded)
        # Les valeurs non étayées restent assagies.
        self.assertNotIn("40 %", grounded)
        self.assertNotIn("30 %", grounded)

    def test_strict_grounding_keeps_markdown_layout(self):
        """Les puces d'une liste ne doivent pas être fondues en un paragraphe."""
        answer = (
            "Voici son bilan :\n"
            "*   **Prix** : 0,27 USD par million.\n"
            "*   **Vitesse** : excellente.\n"
            "*   **Contexte** : 200 000 jetons."
        )
        grounded = ground_strict_answer(
            answer,
            "Tarif publié : 0,27 USD par million.",
        )
        self.assertIn("\n*   **Prix**", grounded)
        self.assertIn("\n*   **Vitesse**", grounded)
        self.assertIn("\n*   **Contexte**", grounded)

    def test_version_number_is_never_cut_in_the_middle(self):
        """« Terminal-Bench 4.0 » ne doit pas être coupé en deux.

        Le point d'un numéro de version n'est pas une fin de phrase : la
        réserve s'insérait sinon AU MILIEU du nombre (« Terminal-Bench
        4.…je n'ai pas de chiffre fiable…0 »).
        """
        answer = (
            "Il surpasse Fable 5.1 sur le Terminal-Bench 4.0 "
            "et obtient 86,1 de moyenne."
        )
        grounded = ground_strict_answer(answer, "Terminal-Bench 4.0 : 86,1.")
        self.assertIn("Terminal-Bench 4.0", grounded)
        self.assertEqual(grounded, answer)

    def test_table_rows_keep_their_grid(self):
        """Dans un tableau, la valeur fautive devient « non vérifié »."""
        answer = (
            "| Métrique | Opus 5.5 | Fable 5.1 |\n"
            "| Entrée | $4.00 | $10.00 |"
        )
        grounded = ground_strict_answer(answer, "Tarif : $4.00 en entrée.")
        self.assertIn("| Entrée | $4.00 | non vérifié |", grounded)
        self.assertNotIn("chiffre fiable", grounded)

    def test_unsupported_value_keeps_its_label(self):
        """La puce garde son intitulé : c'est lui qui dit DE QUOI on ne sait rien.

        Régression observée à l'écran : une puce dont toute la phrase portait un
        chiffre non étayé était remplacée par la seule réserve, sans intitulé —
        le lecteur voyait « …je n'ai pas de chiffre fiable… » sans savoir quel
        point était concerné.
        """
        answer = (
            "* **Version gratuite** : offre limitée à 100 % des tokens.\n"
            "* **Sécurité** : garde-fous renforcés."
        )
        grounded = ground_strict_answer(answer, "Aucune preuve chiffrée.")
        self.assertIn("* **Version gratuite** :", grounded)
        self.assertIn("chiffre fiable", grounded)
        self.assertNotIn("100 %", grounded)
        # La puce suivante, sans chiffre, est intacte.
        self.assertIn("* **Sécurité** : garde-fous renforcés.", grounded)

    def test_softened_sentence_has_single_final_period(self):
        """La ponctuation n'est jamais doublée (« affirmer.. »)."""
        grounded = ground_strict_answer("Le tarif est de 30 USD", "Rien.")
        self.assertNotIn("..", grounded)
        self.assertTrue(grounded.rstrip().endswith("."))

    def test_strict_grounding_without_evidence_does_not_assert_a_price(self):
        grounded = ground_strict_answer(
            "Le tarif est de 30 USD par million de jetons.",
            "",
        )
        self.assertNotIn("30 USD", grounded)
        self.assertIn("chiffre fiable", grounded)

    def test_strict_grounding_without_page_evidence_keeps_clarification(self):
        answer = "Quel benchmark veux-tu comparer ?"
        self.assertEqual(ground_strict_answer(answer, ""), answer)

        mixed = ground_strict_answer(
            "Le prix est de 30 USD. Quel benchmark veux-tu comparer ?",
            "",
        )
        self.assertNotIn("30 USD", mixed)
        self.assertIn("Quel benchmark", mixed)

    def test_conversation_evidence_keeps_numbers_verified_earlier(self):
        """Une relance s'appuie sur les sources déjà citées dans le fil."""
        conversation_sources = [
            {
                "title": "Anthropic — Claude Opus 5.5",
                "snippet": "Opus 5.5 coûte 40 % de moins et est 30 % plus rapide.",
                "url": "https://example.org/opus-5-5",
            }
        ]
        evidence = grounding_evidence_text(
            "",
            [],
            conversation_sources,
        )
        self.assertIn("40 %", evidence)
        answer = "Il est environ 40 % moins cher et 30 % plus rapide."
        self.assertEqual(ground_strict_answer(answer, evidence), answer)

    def test_grounding_evidence_text_merges_blocks_and_bounds_size(self):
        merged = grounding_evidence_text(
            "page lue",
            [{"title": "Titre", "snippet": "Extrait", "url": "https://a.test"}],
            max_chars=1_000,
        )
        self.assertIn("page lue", merged)
        self.assertIn("Titre Extrait https://a.test", merged)

        bounded = grounding_evidence_text("x" * 5_000, max_chars=100)
        self.assertEqual(len(bounded), 100)

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
        query = _fallback_contextual_search_query(messages)
        self.assertIn("lionel messi", query.lower())
        self.assertIn("2026", query)

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
