"""Classification d'intention des requêtes web. Aucun réseau."""

import unittest

from core.mcp.intent import classify_intent, is_tech_news


def _label(value) -> str:
    if hasattr(value, "value"):
        return str(value.value)
    return str(value)


class ClassifyIntentTests(unittest.TestCase):
    def test_contract_queries(self):
        cases = {
            "météo à Lyon demain": "weather",
            "vainqueur de la coupe du monde 2026": "sports",
            "cours du bitcoin": "finance",
            "dernières actualités en France": "news",
            "qui est Ada Lovelace": "knowledge",
            "arxiv paper on speculative decoding": "academic",
            "traceback ImportError pandas": "code",
            "recette de la tartiflette": "general",
        }
        for query, expected in cases.items():
            with self.subTest(query=query):
                self.assertEqual(_label(classify_intent(query)), expected)

    def test_tech_news_detects_new_openai_model(self):
        self.assertTrue(is_tech_news("nouveau modèle OpenAI"))


if __name__ == "__main__":
    unittest.main()
