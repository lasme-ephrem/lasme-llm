import unittest

from core.agent.grounding import (
    is_commercial_comparison,
    requires_strict_grounding,
)


class GroundingClassificationTests(unittest.TestCase):
    def test_empty_query_is_not_strict(self):
        self.assertFalse(requires_strict_grounding(""))
        self.assertFalse(requires_strict_grounding("   "))
        self.assertFalse(is_commercial_comparison(""))

    def test_prices_and_accents_require_strict_grounding(self):
        self.assertTrue(requires_strict_grounding("quel est le prix du modèle"))
        self.assertTrue(requires_strict_grounding("coût des abonnements"))
        self.assertTrue(requires_strict_grounding("compare les coûts"))

    def test_temporal_and_benchmark_markers_are_strict(self):
        self.assertTrue(requires_strict_grounding("dernière version disponible"))
        self.assertTrue(requires_strict_grounding("classement des modèles"))
        self.assertTrue(requires_strict_grounding("benchmarks LLM"))

    def test_volatile_comparison_without_a_price_is_strict_but_not_commercial(self):
        query = "Compare DeepSeek et les modèles d'OpenAI"
        self.assertTrue(requires_strict_grounding(query))
        self.assertFalse(is_commercial_comparison(query))

    def test_commercial_comparison_needs_a_price_and_a_product_or_comparison(self):
        self.assertFalse(is_commercial_comparison("quel est le prix"))
        self.assertTrue(
            is_commercial_comparison(
                "Produit un tableau comparatif des modèles LLM chinois "
                "avec leurs coûts"
            )
        )
        self.assertTrue(
            requires_strict_grounding(
                "Produit un tableau comparatif des modèles LLM chinois "
                "avec leurs coûts"
            )
        )

    def test_stable_knowledge_is_not_grounded(self):
        query = "Explique le théorème de Pythagore"
        self.assertFalse(requires_strict_grounding(query))
        self.assertFalse(is_commercial_comparison(query))


if __name__ == "__main__":
    unittest.main()
