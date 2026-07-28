from __future__ import annotations

import io
import zipfile

from openpyxl import load_workbook
from pypdf import PdfReader

from core.artifacts.exporter import export_artifact


CONTENT = """# Rapport

Une synthèse claire.

| Indicateur | Valeur |
|---|---:|
| Précision | 94 % |
| Latence | 120 ms |

## Étapes

1. Préparer les données
2. Valider le modèle
"""


def test_export_office_and_pdf_formats_are_valid() -> None:
    docx, docx_type, docx_name = export_artifact(
        "Rapport qualité",
        CONTENT,
        kind="document",
        output_format="docx",
    )
    assert docx_type.endswith("wordprocessingml.document")
    assert docx_name.endswith(".docx")
    with zipfile.ZipFile(io.BytesIO(docx)) as archive:
        assert "word/document.xml" in archive.namelist()

    xlsx, _, xlsx_name = export_artifact(
        "Mesures",
        CONTENT,
        kind="table",
        output_format="xlsx",
    )
    workbook = load_workbook(io.BytesIO(xlsx), read_only=True)
    assert xlsx_name.endswith(".xlsx")
    assert workbook.active["A1"].value == "Indicateur"

    pptx, _, pptx_name = export_artifact(
        "Présentation",
        CONTENT,
        kind="presentation",
        output_format="pptx",
    )
    assert pptx_name.endswith(".pptx")
    with zipfile.ZipFile(io.BytesIO(pptx)) as archive:
        assert "ppt/presentation.xml" in archive.namelist()

    pdf, pdf_type, pdf_name = export_artifact(
        "Rapport",
        CONTENT,
        kind="document",
        output_format="pdf",
    )
    assert pdf_type == "application/pdf"
    assert pdf_name.endswith(".pdf")
    assert len(PdfReader(io.BytesIO(pdf)).pages) >= 1


def test_html_export_is_standalone() -> None:
    payload, media_type, filename = export_artifact(
        "Mini application",
        "<main><h1>Bonjour</h1></main>",
        kind="interactive",
        output_format="html",
    )
    source = payload.decode("utf-8")
    assert media_type.startswith("text/html")
    assert filename.endswith(".html")
    assert "<main><h1>Bonjour</h1></main>" in source
