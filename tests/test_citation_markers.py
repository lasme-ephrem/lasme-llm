"""Marqueurs de citation [n] : mécanisme style ChatGPT côté backend.

Couvre les trois pièces du contrat « le modèle cite par [n], le frontend
affiche web_results[n-1] » :
1. numérotation CUMULATIVE de _format_search_results sur plusieurs
   appels web_search d'un même message (compteur SearchResultNumbering) ;
2. positionnement par numéro dans extract_agent_sources (doublon d'URL
   gardé à la plus petite position) ;
3. nettoyage du texte final par sanitize_citation_markers (marqueurs
   valides conservés, hors plage retirés, section « Sources » finale
   supprimée, blocs de code intacts).

Zéro réseau : search_fn mocké, outputs d'outils figés.
"""

import asyncio
import unittest

from chat.server.main import (
    compact_web_source_metadata,
    extract_agent_sources,
    merge_dedup_sources,
    sanitize_citation_markers,
)
from core.agent.tools_web import (
    SearchResultNumbering,
    _format_search_results,
    _run_web_search,
    register_web_tools,
)
from core.agent.tools import ToolRegistry


def _result(title: str, url: str, snippet: str = "Extrait.") -> dict:
    return {"title": title, "url": url, "snippet": snippet}


def search_event(output: str) -> dict:
    return {
        "type": "tool_result",
        "ts": 1.0,
        "id": "c1",
        "name": "web_search",
        "ok": True,
        "output": output,
    }


def fetch_event(output: str) -> dict:
    return {
        "type": "tool_result",
        "ts": 2.0,
        "id": "c2",
        "name": "fetch_pages",
        "ok": True,
        "output": output,
    }


def fake_search(payloads: list):
    """search_fn mocké : un payload par appel, dans l'ordre."""

    def _search(query, max_results, *args, **kwargs):
        return dict(payloads.pop(0)) if payloads else {"results": []}

    return _search


class CumulativeNumberingTests(unittest.TestCase):
    """Numérotation GLOBALE par tour d'agent (1re recherche → [1..n1],
    2e recherche → [n1+1..n1+n2])."""

    def test_format_search_results_cumulative_across_calls(self):
        numbering = SearchResultNumbering()
        first = _format_search_results(
            {
                "results": [
                    _result("Un", "https://a.example.com/1"),
                    _result("Deux", "https://b.example.com/2"),
                ]
            },
            numbering,
        )
        self.assertIn("[1] Un", first)
        self.assertIn("[2] Deux", first)
        # Deuxième appel du MÊME message : la numérotation continue.
        second = _format_search_results(
            {
                "results": [
                    _result("Trois", "https://c.example.com/3"),
                    _result("Quatre", "https://d.example.com/4"),
                ]
            },
            numbering,
        )
        self.assertIn("[3] Trois", second)
        self.assertIn("[4] Quatre", second)
        self.assertNotIn("[1]", second)
        self.assertNotIn("[2] Deux", second)

    def test_failed_search_consumes_no_number(self):
        numbering = SearchResultNumbering()
        empty = _format_search_results(
            {"results": [], "errors": ["timeout"]}, numbering
        )
        self.assertTrue(empty.startswith("Aucun résultat."))
        self.assertEqual(numbering.last, 0)
        after = _format_search_results(
            {"results": [_result("Seul", "https://a.example.com/1")]},
            numbering,
        )
        self.assertIn("[1] Seul", after)

    def test_run_web_search_cumulative_via_mocked_search_fn(self):
        search_fn = fake_search(
            [
                {
                    "results": [
                        _result("Alpha", "https://a.example.com/a"),
                        _result("Beta", "https://b.example.com/b"),
                    ]
                },
                {
                    "results": [
                        _result("Gamma", "https://c.example.com/c"),
                    ]
                },
            ]
        )
        numbering = SearchResultNumbering()

        async def scenario():
            first = await _run_web_search(
                search_fn, {"query": "première", "max_results": 2}, numbering
            )
            second = await _run_web_search(
                search_fn, {"query": "seconde", "max_results": 1}, numbering
            )
            return first, second

        first, second = asyncio.run(scenario())
        self.assertIn("[1] Alpha", first)
        self.assertIn("[2] Beta", first)
        self.assertIn("[3] Gamma", second)

    def test_register_web_tools_uses_per_registry_counter(self):
        registry = ToolRegistry()
        search_fn = fake_search(
            [
                {"results": [_result("Un", "https://a.example.com/1")]},
                {"results": [_result("Deux", "https://b.example.com/2")]},
            ]
        )
        register_web_tools(
            registry, search_fn=search_fn, fetch_fn=lambda url: ""
        )
        # Le compteur vit DANS le registre : une instance par enregistrement
        # (donc par requête de chat), pas de compteur module-level.
        numbering = getattr(registry, "web_result_numbering", None)
        self.assertIsInstance(numbering, SearchResultNumbering)
        tool = registry.get("web_search")
        first = asyncio.run(tool.handler({"query": "a"}))
        second = asyncio.run(tool.handler({"query": "b"}))
        self.assertIn("[1] Un", first)
        self.assertIn("[2] Deux", second)
        # Chaque registre fraîchement construit repart de zéro : aucune
        # fuite de numérotation d'un message assistant à l'autre.
        other = ToolRegistry()
        register_web_tools(
            other, search_fn=search_fn, fetch_fn=lambda url: ""
        )
        self.assertEqual(other.web_result_numbering.last, 0)

    def test_seed_aligns_with_pre_search_sources(self):
        numbering = SearchResultNumbering()
        numbering.seed(3)  # 3 sources déjà trouvées par la pré-recherche
        output = _format_search_results(
            {"results": [_result("Suivant", "https://a.example.com/4")]},
            numbering,
        )
        self.assertIn("[4] Suivant", output)


class ExtractAgentSourcesNumberingTests(unittest.TestCase):
    SEARCH_ONE = (
        "[1] Un\n    https://a.example.com/1\n    Extrait un.\n"
        "[2] Deux\n    https://b.example.com/2\n    Extrait deux.\n"
        "[3] Trois\n    https://c.example.com/3\n    Extrait trois.\n"
    )
    SEARCH_TWO = (
        "[4] Quatre\n    https://d.example.com/4\n    Extrait quatre.\n"
        "[5] Cinq\n    https://e.example.com/5\n    Extrait cinq.\n"
    )

    def test_positions_follow_tool_output_numbers(self):
        sources = extract_agent_sources(
            [search_event(self.SEARCH_ONE), search_event(self.SEARCH_TWO)]
        )
        # La 2e recherche [4][5] occupe les positions 3 et 4 (index 0-based).
        self.assertEqual(
            [source["url"] for source in sources],
            [
                "https://a.example.com/1",
                "https://b.example.com/2",
                "https://c.example.com/3",
                "https://d.example.com/4",
                "https://e.example.com/5",
            ],
        )
        self.assertEqual(sources[3]["number"], 4)
        self.assertEqual(sources[4]["number"], 5)

    def test_gap_renders_none_padding(self):
        # Un seul événement : la recherche numérotée [4][5] — les
        # positions 0-2 n'existent pas dans le journal du run.
        sources = extract_agent_sources([search_event(self.SEARCH_TWO)])
        self.assertIsNone(sources[0])
        self.assertIsNone(sources[1])
        self.assertIsNone(sources[2])
        self.assertEqual(sources[3]["number"], 4)
        self.assertEqual(sources[4]["number"], 5)
        # merge_dedup_sources ignore proprement le remplissage None.
        merged = merge_dedup_sources([], sources)
        self.assertEqual(
            [source["url"] for source in merged],
            ["https://d.example.com/4", "https://e.example.com/5"],
        )

    def test_duplicate_url_keeps_first_smallest_position(self):
        duplicate = (
            "[4] Deux revisité\n    https://b.example.com/2\n    Autre.\n"
            "[5] Cinq\n    https://e.example.com/5\n    Extrait cinq.\n"
        )
        sources = extract_agent_sources(
            [search_event(self.SEARCH_ONE), search_event(duplicate)]
        )
        # Un, Deux, Trois, Cinq : le doublon de « Deux » n'entre pas deux fois.
        self.assertEqual(len([s for s in sources if s]), 4)
        # Première occurrence (numéro 2) conservée à la plus petite position.
        self.assertEqual(sources[1]["number"], 2)
        self.assertEqual(sources[1]["title"], "Deux")
        # La position du doublon (numéro 4) reste vide : aucun [4] ne doit
        # pointer ailleurs silencieusement.
        self.assertIsNone(sources[3])
        self.assertEqual(sources[4]["number"], 5)

    def test_fetch_only_source_appended_after_numbered_block(self):
        fetch_output = (
            "## https://z.example.com/page (120 caractères)\nContenu.\n"
        )
        sources = extract_agent_sources(
            [search_event(self.SEARCH_ONE), fetch_event(fetch_output)]
        )
        self.assertEqual(len(sources), 4)
        self.assertEqual(
            [source["number"] for source in sources[:3]], [1, 2, 3]
        )
        # La page fetchée sans numéro n'a pas de marqueur citable : en fin
        # de liste, son décalage n'affecte aucun [n].
        self.assertIsNone(sources[3].get("number"))
        self.assertEqual(sources[3]["url"], "https://z.example.com/page")

    def test_search_title_promotes_unnumbered_fetch_entry(self):
        fetch_first = fetch_event(
            "## https://hf.co/docs (800 caractères)\nContenu…"
        )
        search_after = search_event(
            "[1] Transformers : documentation\n    https://www.hf.co/docs/\n"
            "    Extrait.\n"
        )
        sources = extract_agent_sources([fetch_first, search_after])
        self.assertEqual(len(sources), 1)
        self.assertEqual(sources[0]["number"], 1)
        self.assertEqual(sources[0]["title"], "Transformers : documentation")

    def test_compact_persists_numbers(self):
        sources = extract_agent_sources(
            [search_event(self.SEARCH_ONE), search_event(self.SEARCH_TWO)]
        )
        compact = compact_web_source_metadata(sources)
        rows = compact["web_results"]
        self.assertEqual(
            [row["number"] for row in rows], [1, 2, 3, 4, 5]
        )
        # Source sans numéro explicite : la position (1-based) fait office.
        fallback = compact_web_source_metadata(
            [{"title": "T", "url": "https://x.example.com/", "engine": "ddg"}]
        )
        self.assertEqual(fallback["web_results"][0]["number"], 1)


class SanitizeCitationMarkersTests(unittest.TestCase):
    def test_valid_markers_are_preserved(self):
        text = "Voici le fait établi [1]. Autre point [2][5]."
        self.assertEqual(sanitize_citation_markers(text, 5), text)

    def test_out_of_range_and_invalid_markers_removed(self):
        cleaned = sanitize_citation_markers("Voir [1] puis [9].", 5)
        self.assertEqual(cleaned, "Voir [1] puis.")
        # n < 1 (zéro) : hors plage.
        cleaned = sanitize_citation_markers("A [0], B [2].", 3)
        self.assertEqual(cleaned, "A, B [2].")

    def test_zero_sources_removes_every_marker(self):
        cleaned = sanitize_citation_markers(
            "Réponse locale [1] sans source [2] ni [12].", 0
        )
        self.assertEqual(cleaned, "Réponse locale sans source ni.")
        self.assertNotIn("[", cleaned)

    def test_marker_lists_checked_entry_wise(self):
        # Tous les numéros du marqueur dans la plage : conservé.
        self.assertEqual(
            sanitize_citation_markers("Fait [1,3] établi.", 3),
            "Fait [1,3] établi.",
        )
        # Au moins un hors plage : tout le marqueur part.
        self.assertEqual(
            sanitize_citation_markers("Fait [1,9] douteux.", 3),
            "Fait douteux.",
        )

    def test_final_sources_section_removed(self):
        text = (
            "Réponse courte [1].\n\n"
            "Sources :\n"
            "- [Un](https://a.example.com/1)\n"
            "- https://b.example.com/2\n"
        )
        self.assertEqual(
            sanitize_citation_markers(text, 2), "Réponse courte [1]."
        )
        headings = (
            "Sources",
            "Sources :",
            "## Sources",
            "Références :",
            "**Sources :**",
        )
        for heading in headings:
            text = f"Réponse [1].\n\n{heading}\n- https://a.example.com/1\n"
            self.assertEqual(
                sanitize_citation_markers(text, 1),
                "Réponse [1].",
                heading,
            )

    def test_sources_section_kept_when_followed_by_prose(self):
        # Prudent : une section « Sources » suivie d'autre prose n'est pas
        # une section finale — elle est conservée.
        text = "Réponse.\n\nSources :\n- a\n\nAutre paragraphe [1]."
        self.assertEqual(sanitize_citation_markers(text, 1), text)

    def test_code_blocks_untouched(self):
        text = (
            "Du texte [1].\n"
            "```python\n"
            "x = [1]\n"
            "rows = [2]\n"
            "data = [99]\n"
            "```\n"
            "Encore [2]."
        )
        self.assertEqual(sanitize_citation_markers(text, 2), text)
        # Sans source : les marqueurs du prose partent, le code reste.
        cleaned = sanitize_citation_markers(text, 0)
        self.assertIn("x = [1]", cleaned)
        self.assertIn("rows = [2]", cleaned)
        self.assertIn("data = [99]", cleaned)
        self.assertNotIn("Du texte [1]", cleaned)
        self.assertNotIn("Encore [2]", cleaned)

    def test_inline_code_untouched(self):
        cleaned = sanitize_citation_markers("Code `[1]` intact [1].", 0)
        self.assertEqual(cleaned, "Code `[1]` intact.")


if __name__ == "__main__":
    unittest.main()
