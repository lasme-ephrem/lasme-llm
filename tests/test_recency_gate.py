"""Tests du classificateur de sensibilité temporelle (recency gate).

Vient du cas de production : « Cherche sur le web qui a remporté le
dernier Ballon d'Or » (septembre 2026) répondue de mémoire (« Rodri
2024 ») car aucun détecteur ne classait la question comme sensible au
temps. `is_recency_sensitive` doit maintenant classer ces questions en
True pour forcer la recherche web côté /api/chat/stream.
"""

import unittest


class RecencyGatePositiveTests(unittest.TestCase):
    """Questions qui DOIVENT déclencher la recherche web forcée."""

    POSITIVES = [
        "qui a remporté le dernier Ballon d'Or",
        "quelle est la dernière version de Python",
        "qui est le président des États-Unis",
        "cours du bitcoin aujourd'hui",
        "météo Paris",
        "classement Ligue 1",
        "qui a gagné la finale 2025",
    ]

    def _is_recency_sensitive(self, query):
        from chat.server.main import is_recency_sensitive

        return is_recency_sensitive(query)

    def test_required_positive_queries_trigger(self):
        for query in self.POSITIVES:
            with self.subTest(query=query):
                self.assertTrue(self._is_recency_sensitive(query))

    def test_matching_is_case_and_accent_insensitive(self):
        # Normalisation NFD : majuscules, accents manquants ou apostrophe
        # typographique ne doivent pas empêcher la détection.
        self.assertTrue(
            self._is_recency_sensitive("QUELLE EST LA DERNIERE VERSION DE RUST")
        )
        self.assertTrue(
            self._is_recency_sensitive("Qui a remporté le dernier Ballon d’Or ?")
        )
        self.assertTrue(self._is_recency_sensitive("METEO Paris maintenant"))

    def test_each_recency_family_matches(self):
        samples = {
            "superlatif_temporel": "que se passe-t-il en ce moment ?",
            "question_volatile": "qui est le premier ministre du Japon ?",
            "evenement_recurrent": "qui a reçu le prix Nobel de la paix ?",
            "donnee_vivante": "quel est le taux de chômage en France ?",
            "fraicheur_produit": "y a-t-il une nouvelle version du navigateur ?",
            "annee_explicite": "que s'est-il passé en 2026 ?",
        }
        for family, query in samples.items():
            with self.subTest(family=family):
                self.assertTrue(self._is_recency_sensitive(query))


class RecencyGateNegativeTests(unittest.TestCase):
    """Questions de connaissance stable qui NE doivent PAS déclencher."""

    NEGATIVES = [
        "explique la photosynthèse",
        "écris un poème sur la mer",
        "qu'est-ce que la constante de Planck",
        "resume Guerre et Paix",
        "convertis 5 km en miles",
    ]

    def test_required_negative_queries_do_not_trigger(self):
        from chat.server.main import is_recency_sensitive

        for query in self.NEGATIVES:
            with self.subTest(query=query):
                self.assertFalse(is_recency_sensitive(query))

    def test_old_history_and_stable_knowledge_do_not_trigger(self):
        from chat.server.main import is_recency_sensitive

        self.assertFalse(
            is_recency_sensitive("explique la bataille de Waterloo en 1815")
        )
        self.assertFalse(is_recency_sensitive("démontre le théorème de Pythagore"))
        self.assertFalse(is_recency_sensitive(""))

    def test_returns_a_real_boolean(self):
        from chat.server.main import is_recency_sensitive

        self.assertIs(is_recency_sensitive("météo Paris"), True)
        self.assertIs(is_recency_sensitive("explique la photosynthèse"), False)


if __name__ == "__main__":
    unittest.main()
