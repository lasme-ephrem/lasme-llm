import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pymupdf
from PIL import Image, ImageDraw

from chat.server import main as server_main
from core.rag.store import RAGDocumentStore


def scanned_pdf_bytes() -> bytes:
    image = Image.new("RGB", (900, 500), "white")
    draw = ImageDraw.Draw(image)
    draw.text(
        (40, 60),
        "REFERENCE VISUELLE ORION-742\nVentes 2026 : 125 000 EUR",
        fill="black",
    )
    encoded = io.BytesIO()
    image.save(encoded, format="PNG")
    document = pymupdf.open()
    page = document.new_page(width=900, height=500)
    page.insert_image(page.rect, stream=encoded.getvalue())
    payload = document.tobytes()
    document.close()
    return payload


class PDFVisionPipelineTests(unittest.IsolatedAsyncioTestCase):
    async def test_scanned_pdf_is_rendered_and_indexed_by_local_vision(self):
        content = scanned_pdf_bytes()
        rendered, page_count = RAGDocumentStore.render_pdf_pages_for_vision(
            content
        )
        self.assertEqual(page_count, 1)
        self.assertEqual(rendered[0][0], 1)
        self.assertEqual(rendered[0][2], "scan")

        with tempfile.TemporaryDirectory() as temp_dir:
            store = RAGDocumentStore(Path(temp_dir) / "rag.db")
            fake_reply = {
                "message": {
                    "content": (
                        "TEXTE VISIBLE\nREFERENCE VISUELLE ORION-742\n"
                        "DONNÉES STRUCTURÉES\nVentes 2026 : 125 000 EUR"
                    )
                }
            }
            with (
                patch.object(server_main, "rag_store", store),
                patch.object(
                    RAGDocumentStore,
                    "ocr_capabilities",
                    return_value={"available": False},
                ),
                patch.object(
                    server_main.client,
                    "chat",
                    new=AsyncMock(return_value=fake_reply),
                ),
            ):
                chunks, metadata = await server_main._index_project_pdf(
                    scope_id="project-a",
                    filename="scan.pdf",
                    content=content,
                    file_id="scan-file",
                    mime_type="application/pdf",
                )

            self.assertGreater(chunks, 0)
            self.assertEqual(metadata["indexer"], "vision_pdf")
            results = store.search(
                "project-a",
                "ORION-742 ventes 125000",
                file_ids=["scan-file"],
            )
            self.assertTrue(results)
            self.assertEqual(results[0]["page"], 1)


if __name__ == "__main__":
    unittest.main()
