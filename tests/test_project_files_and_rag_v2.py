import io
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from docx import Document
from openpyxl import Workbook
from pptx import Presentation

from chat.server import main as server_main
from core.files.store import ProjectFileStore
from core.rag.store import RAGDocumentStore


class ProjectFileStoreTests(unittest.TestCase):
    def test_original_is_preserved_and_duplicate_is_reused(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            store = ProjectFileStore(
                db_path=root / "files.db",
                storage_root=root / "originals",
            )
            content = b"# Notes\nUne source documentaire unique."
            record, duplicate = store.add(
                project_id="project-a",
                filename="../notes.md",
                content=content,
                mime_type="text/markdown",
            )
            self.assertFalse(duplicate)
            self.assertEqual(record["filename"], "notes.md")
            self.assertEqual(store.read(record["id"]), content)

            reused, duplicate = store.add(
                project_id="project-a",
                filename="copie.md",
                content=content,
                mime_type="text/markdown",
            )
            self.assertTrue(duplicate)
            self.assertEqual(reused["id"], record["id"])
            self.assertEqual(len(store.list("project-a")), 1)

    def test_deletion_removes_metadata_and_original(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            store = ProjectFileStore(
                db_path=root / "files.db",
                storage_root=root / "originals",
            )
            record, _ = store.add(
                project_id="project-a",
                filename="document.txt",
                content=b"Contenu",
            )
            path = store.path_for(record["id"])
            self.assertIsNotNone(path)
            self.assertTrue(path.is_file())
            self.assertTrue(store.delete(record["id"]))
            self.assertIsNone(store.get(record["id"]))
            self.assertFalse(path.exists())

    def test_spoofed_mime_cannot_turn_html_into_an_inline_pdf(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            store = ProjectFileStore(
                db_path=root / "files.db",
                storage_root=root / "originals",
            )
            with self.assertRaisesRegex(ValueError, "valid PDF"):
                store.add(
                    project_id="project-a",
                    filename="facture.pdf",
                    content=b"<html><script>window.top.pwned=true</script></html>",
                    mime_type="text/html",
                )

            markdown, _ = store.add(
                project_id="project-a",
                filename="notes.md",
                content=b"# Notes\nContenu fiable.",
                mime_type="text/html",
            )
            self.assertEqual(markdown["mime_type"], "text/markdown")

    def test_concurrent_duplicate_uploads_converge_to_one_original(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            store = ProjectFileStore(
                db_path=root / "files.db",
                storage_root=root / "originals",
            )
            content = b"# Source\nContenu concurrent identique."

            def upload(index):
                return store.add(
                    project_id="project-a",
                    filename=f"source-{index}.md",
                    content=content,
                )

            with ThreadPoolExecutor(max_workers=6) as executor:
                outcomes = list(executor.map(upload, range(12)))

            self.assertEqual(
                len({record["id"] for record, _ in outcomes}),
                1,
            )
            self.assertEqual(len(store.list("project-a")), 1)


class RichDocumentRAGTests(unittest.TestCase):
    @staticmethod
    def _word_bytes() -> bytes:
        document = Document()
        document.add_heading("Politique qualité", level=1)
        document.add_paragraph("Le seuil interne de conformité est de 97 pour cent.")
        table = document.add_table(rows=2, cols=2)
        table.cell(0, 0).text = "Indicateur"
        table.cell(0, 1).text = "Valeur"
        table.cell(1, 0).text = "Précision"
        table.cell(1, 1).text = "97 %"
        output = io.BytesIO()
        document.save(output)
        return output.getvalue()

    @staticmethod
    def _excel_bytes() -> bytes:
        workbook = Workbook()
        sheet = workbook.active
        sheet.title = "Ventes 2026"
        sheet.append(["Région", "Chiffre d'affaires"])
        sheet.append(["Europe", 125000])
        output = io.BytesIO()
        workbook.save(output)
        return output.getvalue()

    @staticmethod
    def _powerpoint_bytes() -> bytes:
        deck = Presentation()
        slide = deck.slides.add_slide(deck.slide_layouts[1])
        slide.shapes.title.text = "Plan Horizon"
        slide.placeholders[1].text = "Lancement pilote prévu en septembre 2026."
        output = io.BytesIO()
        deck.save(output)
        return output.getvalue()

    def test_word_excel_and_powerpoint_are_searchable(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = RAGDocumentStore(Path(temp_dir) / "rag.db")
            fixtures = (
                ("qualite.docx", self._word_bytes(), "conformité précision"),
                ("ventes.xlsx", self._excel_bytes(), "Europe 125000"),
                ("horizon.pptx", self._powerpoint_bytes(), "septembre 2026"),
            )
            for filename, content, query in fixtures:
                with self.subTest(filename=filename):
                    file_id = f"id-{filename}"
                    self.assertGreater(
                        store.add_document(
                            "project-a",
                            filename,
                            content,
                            file_id=file_id,
                        ),
                        0,
                    )
                    results = store.search(
                        "project-a",
                        query,
                        top_k=3,
                        file_ids=[file_id],
                    )
                    self.assertTrue(results)
                    self.assertEqual(results[0]["doc_name"], filename)

    def test_visual_analysis_can_be_indexed_without_ocr(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = RAGDocumentStore(Path(temp_dir) / "rag.db")
            store.add_extracted_text(
                "project-a",
                "graphique.png",
                (
                    "GRAPHIQUE OU SCHÉMA\n"
                    "Les ventes passent de 40 en janvier à 85 en mars."
                ),
                file_id="image-1",
                mime_type="image/png",
            )
            results = store.search(
                "project-a",
                "ventes mars 85",
                file_ids=["image-1"],
            )
            self.assertTrue(results)
            self.assertEqual(results[0]["section"], "Analyse visuelle")

    def test_unrelated_feature_hash_collision_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = RAGDocumentStore(Path(temp_dir) / "rag.db")
            store.add_document(
                "project-a",
                "conditions.md",
                (
                    "Conditions générales de vente et garanties légales. "
                    "Le consommateur dispose d'un droit de rétractation."
                ).encode("utf-8"),
            )
            self.assertEqual(
                store.search(
                    "project-a",
                    "nombre de buts de Lionel Messi en 2026",
                ),
                [],
            )

    def test_project_report_intent_returns_representative_file_content(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = RAGDocumentStore(Path(temp_dir) / "rag.db")
            store.add_document(
                "project-a",
                "budget.md",
                b"# Budget\nLe budget du projet est de 120 000 euros.",
                file_id="budget-file",
            )
            store.add_document(
                "project-a",
                "planning.md",
                b"# Planning\nLa livraison finale est prevue en novembre.",
                file_id="planning-file",
            )

            results = store.search_scopes(
                ["project-a"],
                "Fais un rapport des fichiers dans ce projet",
                top_k=8,
            )

            self.assertEqual(
                {result["doc_name"] for result in results},
                {"budget.md", "planning.md"},
            )
            self.assertTrue(all(result.get("coverage") for result in results))

    def test_explain_this_document_uses_the_selected_file_overview(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = RAGDocumentStore(Path(temp_dir) / "rag.db")
            store.add_document(
                "project-a",
                "rapport.md",
                (
                    "# Introduction\nObjectif principal.\n\n"
                    "# Conclusion\nResultat final."
                ).encode("utf-8"),
                file_id="report-file",
            )
            store.add_document(
                "project-a",
                "hors-sujet.md",
                b"Ce contenu ne doit pas etre retenu.",
                file_id="other-file",
            )

            results = store.search_scopes(
                ["project-a"],
                "Explique ce document de A à Z",
                top_k=8,
                file_ids=["report-file"],
            )

            self.assertTrue(results)
            self.assertEqual(
                {result["file_id"] for result in results},
                {"report-file"},
            )

    def test_legacy_index_remains_visible_previewable_and_targetable(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = RAGDocumentStore(Path(temp_dir) / "rag.db")
            store.add_document(
                "project-a",
                "ancien.md",
                b"# Archive\nLe code de reference est ORION-742.",
            )
            document = store.list_documents("project-a")[0]
            self.assertIsNone(document["file_id"])
            self.assertEqual(document["scope_id"], "project-a")
            self.assertTrue(store.get_document(document["id"]))
            self.assertIn(
                "ORION-742",
                store.preview_indexed_document(document["id"])[0]["text"],
            )
            self.assertTrue(
                store.search(
                    "project-a",
                    "ORION-742",
                    file_ids=[document["id"]],
                )
            )
            self.assertTrue(
                store.rename_document(document["id"], "archive-renommee.md")
            )
            self.assertEqual(
                store.get_document(document["id"])["filename"],
                "archive-renommee.md",
            )


class FastDocumentIndexingTests(unittest.IsolatedAsyncioTestCase):
    async def test_text_pdf_skips_slow_visual_pass(self):
        with (
            patch.object(
                server_main.rag_store,
                "add_document",
                return_value=4,
            ),
            patch.object(
                server_main.rag_store,
                "render_pdf_pages_for_vision",
            ) as render_for_vision,
        ):
            chunks, metadata = await server_main._index_project_pdf(
                scope_id="project-a",
                filename="rapport.pdf",
                content=b"%PDF-1.7\n",
                file_id="file-a",
                mime_type="application/pdf",
            )

        self.assertEqual(chunks, 4)
        self.assertEqual(metadata["indexer"], "document_parser")
        self.assertEqual(metadata["vision_status"], "not_required")
        render_for_vision.assert_not_called()


if __name__ == "__main__":
    unittest.main()
