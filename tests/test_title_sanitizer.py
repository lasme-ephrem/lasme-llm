"""Sanitisation des titres de conversation générés par le modèle."""

import unittest

from chat.server.main import sanitize_generated_title


class SanitizeGeneratedTitleTests(unittest.TestCase):
    def test_first_letter_capitalized(self):
        self.assertEqual(
            sanitize_generated_title("quel est le dernier modèle en date"),
            "Quel est le dernier modèle en date",
        )

    def test_accented_first_letter(self):
        self.assertEqual(sanitize_generated_title("évolution du marché"), "Évolution du marché")

    def test_french_apostrophe_is_preserved(self):
        self.assertEqual(
            sanitize_generated_title("explication du théorème d'universalité"),
            "Explication du théorème d'universalité",
        )

    def test_strips_wrapping_quotes(self):
        self.assertEqual(
            sanitize_generated_title('"Diagonalisation des matrices"'),
            "Diagonalisation des matrices",
        )

    def test_strips_titre_prefix(self):
        self.assertEqual(
            sanitize_generated_title("Titre : Calcul des nombres premiers"),
            "Calcul des nombres premiers",
        )

    def test_strips_trailing_punctuation_and_newlines(self):
        self.assertEqual(
            sanitize_generated_title("Cours sur la diagonalisation.\n\nVoici..."),
            "Cours sur la diagonalisation",
        )

    def test_collapses_whitespace(self):
        self.assertEqual(
            sanitize_generated_title("  Calcul   des   nombres  "),
            "Calcul des nombres",
        )

    def test_empty_returns_empty(self):
        self.assertEqual(sanitize_generated_title('""'), "")
        self.assertEqual(sanitize_generated_title(""), "")


if __name__ == "__main__":
    unittest.main()
