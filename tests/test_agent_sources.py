"""Sources découvertes par l'agent : parsing des tool_result et fusion.

Couvre extract_agent_sources / merge_dedup_sources / normalize_source_url
et la persistance compact_web_source_metadata du résultat fusionné.
Aucun réseau : les outputs d'outils sont des échantillons figés observés
en production (formats de _format_search_results et _run_fetch_pages).
"""

import unittest

from chat.server.main import (
    compact_web_source_metadata,
    extract_agent_sources,
    merge_dedup_sources,
    normalize_source_url,
)

# Format réel d'un output web_search (liens numérotés de
# _format_search_results, ligne d'avertissement entre les entrées).
SEARCH_OUTPUT = """[1] Releases · ggml-org/llama.cpp · GitHub
    https://github.com/ggml-org/llama.cpp/releases
    Téléchargez les dernières versions de llama.cpp…
⚠ Extraits insuffisants pour répondre : appelle fetch_pages sur les URLs pertinentes avant de répondre.
[2] Home · ggml-org/llama.cpp
    https://github.com/ggml-org/llama.cpp/
    Inférence de modèles LLaMA en C/C++ pur.
⚠ Extraits insuffisants pour répondre : appelle fetch_pages sur les URLs pertinentes avant de répondre.
[3] Transformers : documentation
    https://hf.co/docs
    La bibliothèque Transformers, documentation officielle.
"""

# Format réel d'un output fetch_pages (« ## url (n caractères) ») : la
# première URL enrichit l'entrée web_search existante, la deuxième est une
# page lue sans recherche préalable, la troisième a échoué (non lue).
FETCH_OUTPUT = """## https://github.com/ggml-org/llama.cpp/releases (11746 caractères)
## Navigation Menu

# Search code, datasets...

## https://hf.co/docs (800 caractères)
Transformers documentation…

## https://down.example.org/page (24 caractères)
ERREUR: HTTPError: 500 Server Error
"""


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


class ExtractAgentSourcesTests(unittest.TestCase):
    def test_parse_web_search_output(self):
        sources = extract_agent_sources([search_event(SEARCH_OUTPUT)])
        self.assertEqual(len(sources), 3)
        self.assertEqual(
            sources[0],
            {
                "title": "Releases · ggml-org/llama.cpp · GitHub",
                "url": "https://github.com/ggml-org/llama.cpp/releases",
                "engine": "agent",
                "snippet": "",
            },
        )
        # L'ordre des résultats est conservé et l'avertissement entre les
        # entrées ne casse pas le parsing.
        self.assertEqual(sources[1]["url"], "https://github.com/ggml-org/llama.cpp/")
        self.assertEqual(sources[2]["title"], "Transformers : documentation")
        for source in sources:
            self.assertEqual(source["engine"], "agent")
            self.assertEqual(source["snippet"], "")

    def test_parse_fetch_pages_enriches_without_duplicates(self):
        sources = extract_agent_sources(
            [search_event(SEARCH_OUTPUT), fetch_event(FETCH_OUTPUT)]
        )
        urls = [source["url"] for source in sources]
        # Pas de doublon : l'URL fetchée déjà présente dans web_search ne
        # crée pas une seconde entrée.
        self.assertEqual(len(urls), len(set(urls)))
        self.assertEqual(
            urls,
            [
                "https://github.com/ggml-org/llama.cpp/releases",
                "https://github.com/ggml-org/llama.cpp/",
                "https://hf.co/docs",
            ],
        )
        github = sources[0]
        # Le titre réel du web_search est conservé face au titre déduit
        # de l'URL (« Releases »).
        self.assertEqual(github["title"], "Releases · ggml-org/llama.cpp · GitHub")
        # La page fetchée en plus reçoit son titre ; la section ERREUR
        # (page non lue) n'est pas une source.
        self.assertEqual(sources[2]["url"], "https://hf.co/docs")
        self.assertNotIn("https://down.example.org/page", urls)

    def test_search_title_replaces_url_derived_title(self):
        fetch_first = fetch_event("## https://hf.co/docs (800 caractères)\nContenu…")
        search_after = search_event(
            "[1] Transformers : documentation\n    https://www.hf.co/docs/\n    Extrait."
        )
        sources = extract_agent_sources([fetch_first, search_after])
        self.assertEqual(len(sources), 1)
        self.assertEqual(sources[0]["title"], "Transformers : documentation")

    def test_ignores_other_events_and_empty_outputs(self):
        events = [
            {"type": "turn_start", "ts": 0.0, "turn": 1},
            {"type": "tool_result", "ts": 0.5, "name": "calculate", "output": "4"},
            {"type": "content_delta", "ts": 0.7, "text": "Réponse"},
            search_event("Aucun résultat."),
            fetch_event(""),
            {"type": "final", "ts": 1.0, "content": "Fait."},
        ]
        self.assertEqual(extract_agent_sources(events), [])
        self.assertEqual(extract_agent_sources([]), [])
        self.assertEqual(extract_agent_sources(None), [])

    def test_truncates_title_and_url(self):
        output = (
            "[1] " + "a" * 400 + "\n"
            "    https://example.org/" + "b" * 2100 + "\n"
            "    Extrait."
        )
        sources = extract_agent_sources([search_event(output)])
        self.assertEqual(len(sources), 1)
        self.assertEqual(len(sources[0]["title"]), 300)
        self.assertEqual(len(sources[0]["url"]), 2000)


class NormalizeAndMergeTests(unittest.TestCase):
    def test_normalize_source_url(self):
        self.assertEqual(
            normalize_source_url("https://www.Example.com/Page/"),
            normalize_source_url("http://example.com/Page"),
        )
        self.assertEqual(
            normalize_source_url("https://example.com/Page/"), "example.com/Page"
        )
        # La query distingue deux sources, pas le fragment ni le schéma.
        self.assertNotEqual(
            normalize_source_url("https://example.com/a?q=1"),
            normalize_source_url("https://example.com/a?q=2"),
        )
        self.assertEqual(normalize_source_url(""), "")
        self.assertEqual(normalize_source_url(None), "")

    def test_merge_keeps_pre_search_priority_and_order(self):
        pre_search = [
            {"title": "Source pré 1", "url": "https://a.example.com/one", "engine": "ddg", "snippet": "x"},
            {"title": "Source pré 2", "url": "https://b.example.com/two", "engine": "brave", "snippet": "y"},
        ]
        agent = [
            # Doublon normalisé de la source pré-recherche : écarté.
            {"title": "Doublon agent", "url": "http://www.b.example.com/two/", "engine": "agent", "snippet": ""},
            {"title": "Nouvelle agent 1", "url": "https://c.example.com/three", "engine": "agent", "snippet": ""},
            {"title": "Nouvelle agent 2", "url": "https://d.example.com/four", "engine": "agent", "snippet": ""},
        ]
        merged = merge_dedup_sources(pre_search, agent)
        self.assertEqual(len(merged), 4)
        # Priorité pré-recherche : entrées et ordre d'origine conservés.
        self.assertEqual(merged[0], pre_search[0])
        self.assertEqual(merged[1], pre_search[1])
        # Ajouts agent en fin, dans l'ordre.
        self.assertEqual(merged[2]["title"], "Nouvelle agent 1")
        self.assertEqual(merged[3]["title"], "Nouvelle agent 2")

    def test_merge_handles_empty_and_invalid_inputs(self):
        self.assertEqual(merge_dedup_sources([], []), [])
        self.assertEqual(merge_dedup_sources(None, [{"title": "T", "url": "https://e.com/"}]), [
            {"title": "T", "url": "https://e.com/"}
        ])
        self.assertEqual(merge_dedup_sources([{"url": ""}], [{"nope": 1}]), [])


class CompactMergedSourcesTests(unittest.TestCase):
    def test_compact_web_source_metadata_on_merged_result(self):
        pre_search = {
            "title": "Source pré-recherche",
            "url": "https://www.Example.com/Page/",
            "engine": "ddg",
            "snippet": "Extrait vérifié.",
        }
        agent_sources = extract_agent_sources(
            [search_event(SEARCH_OUTPUT), fetch_event(FETCH_OUTPUT)]
        )
        merged = merge_dedup_sources([pre_search], agent_sources)
        compact = compact_web_source_metadata(merged)
        self.assertIn("web_results", compact)
        rows = compact["web_results"]
        self.assertEqual(len(rows), 4)
        self.assertEqual(
            rows[0],
            {
                "title": "Source pré-recherche",
                "url": "https://www.Example.com/Page/",
                "engine": "ddg",
                "snippet": "Extrait vérifié.",
            },
        )
        self.assertEqual(rows[1]["engine"], "agent")
        # hf.co/docs : vu par le web_search de l'agent, son vrai titre
        # prime sur le titre déduit de l'URL par fetch_pages.
        self.assertEqual(rows[3]["title"], "Transformers : documentation")
        for row in rows:
            self.assertEqual(
                set(row.keys()), {"title", "url", "engine", "snippet"}
            )


if __name__ == "__main__":
    unittest.main()
