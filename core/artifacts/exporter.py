from __future__ import annotations

import csv
import datetime
import html
import io
import json
import re
from typing import Any, Dict, List, Sequence, Tuple

from docx import Document
from docx.shared import Inches, Pt
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from pptx import Presentation
from pptx.util import Inches as PptxInches
from pptx.util import Pt as PptxPt
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    Paragraph,
    Preformatted,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)


EXPORT_FORMATS = {
    "md",
    "txt",
    "html",
    "docx",
    "xlsx",
    "pptx",
    "pdf",
    "csv",
    "svg",
}


def safe_filename(title: str, extension: str) -> str:
    stem = re.sub(r"[^a-zA-Z0-9_-]+", "-", title or "").strip("-")
    return f"{stem or 'artefact'}.{extension}"


def _strip_inline_markdown(value: str) -> str:
    text = re.sub(r"`([^`]+)`", r"\1", value)
    text = re.sub(r"\*\*([^*]+)\*\*", r"\1", text)
    text = re.sub(r"__([^_]+)__", r"\1", text)
    text = re.sub(r"(?<!\*)\*([^*]+)\*(?!\*)", r"\1", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    return text.strip()


def _markdown_blocks(content: str) -> List[Tuple[str, object]]:
    lines = str(content or "").replace("\r\n", "\n").split("\n")
    blocks: List[Tuple[str, object]] = []
    paragraph: List[str] = []
    index = 0

    def flush_paragraph() -> None:
        if paragraph:
            blocks.append(("paragraph", " ".join(part.strip() for part in paragraph)))
            paragraph.clear()

    while index < len(lines):
        line = lines[index]
        stripped = line.strip()
        if stripped.startswith("```"):
            flush_paragraph()
            language = stripped[3:].strip()
            code: List[str] = []
            index += 1
            while index < len(lines) and not lines[index].strip().startswith("```"):
                code.append(lines[index])
                index += 1
            blocks.append(("code", (language, "\n".join(code))))
        elif re.match(r"^#{1,6}\s+", stripped):
            flush_paragraph()
            level = len(stripped) - len(stripped.lstrip("#"))
            blocks.append(("heading", (level, _strip_inline_markdown(stripped[level:].strip()))))
        elif re.match(r"^\s*[-*+]\s+", line):
            flush_paragraph()
            blocks.append(("bullet", _strip_inline_markdown(re.sub(r"^\s*[-*+]\s+", "", line))))
        elif re.match(r"^\s*\d+[.)]\s+", line):
            flush_paragraph()
            blocks.append(("number", _strip_inline_markdown(re.sub(r"^\s*\d+[.)]\s+", "", line))))
        elif (
            "|" in stripped
            and index + 1 < len(lines)
            and re.match(r"^\s*\|?\s*:?-{3,}", lines[index + 1])
        ):
            flush_paragraph()
            table_lines = [stripped]
            index += 2
            while index < len(lines) and "|" in lines[index]:
                table_lines.append(lines[index].strip())
                index += 1
            rows = [
                [_strip_inline_markdown(cell) for cell in row.strip("|").split("|")]
                for row in table_lines
            ]
            blocks.append(("table", rows))
            continue
        elif not stripped:
            flush_paragraph()
        else:
            paragraph.append(stripped)
        index += 1
    flush_paragraph()
    return blocks


def _first_table(content: str) -> List[List[str]]:
    table = next(
        (value for kind, value in _markdown_blocks(content) if kind == "table"),
        None,
    )
    if table:
        return table  # type: ignore[return-value]
    rows = list(csv.reader(io.StringIO(content)))
    return [row for row in rows if any(cell.strip() for cell in row)]


def export_docx(title: str, content: str) -> bytes:
    document = Document()
    section = document.sections[0]
    section.top_margin = Inches(0.7)
    section.bottom_margin = Inches(0.7)
    document.add_heading(title or "Artefact", 0)
    for kind, value in _markdown_blocks(content):
        if kind == "heading":
            level, text = value  # type: ignore[misc]
            document.add_heading(text, level=min(int(level), 4))
        elif kind in {"bullet", "number"}:
            document.add_paragraph(
                str(value),
                style="List Bullet" if kind == "bullet" else "List Number",
            )
        elif kind == "code":
            language, code = value  # type: ignore[misc]
            paragraph = document.add_paragraph()
            if language:
                run = paragraph.add_run(f"{str(language).upper()}\n")
                run.bold = True
                run.font.size = Pt(8)
            run = paragraph.add_run(str(code))
            run.font.name = "Consolas"
            run.font.size = Pt(9)
        elif kind == "table":
            rows = value  # type: ignore[assignment]
            if not rows:
                continue
            table = document.add_table(rows=len(rows), cols=max(len(row) for row in rows))
            table.style = "Table Grid"
            for row_index, row in enumerate(rows):
                for column_index, cell in enumerate(row):
                    target = table.cell(row_index, column_index)
                    target.text = str(cell)
                    if row_index == 0:
                        for run in target.paragraphs[0].runs:
                            run.bold = True
        else:
            document.add_paragraph(_strip_inline_markdown(str(value)))
    output = io.BytesIO()
    document.save(output)
    return output.getvalue()


def export_xlsx(title: str, content: str) -> bytes:
    workbook = Workbook()
    worksheet = workbook.active
    worksheet.title = re.sub(r"[:\\/?*\[\]]", "-", title or "Données")[:31]
    rows = _first_table(content)
    if not rows:
        rows = [["Contenu"], [_strip_inline_markdown(content)]]
    for row in rows:
        worksheet.append(row)
    for cell in worksheet[1]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="0BAE83")
        cell.alignment = Alignment(vertical="center")
    worksheet.freeze_panes = "A2"
    worksheet.auto_filter.ref = worksheet.dimensions
    for column in worksheet.columns:
        length = min(max(len(str(cell.value or "")) for cell in column) + 2, 48)
        worksheet.column_dimensions[column[0].column_letter].width = max(10, length)
    output = io.BytesIO()
    workbook.save(output)
    return output.getvalue()


def _slide_sections(content: str) -> List[Tuple[str, List[str]]]:
    sections: List[Tuple[str, List[str]]] = []
    current_title = "Synthèse"
    body: List[str] = []
    for kind, value in _markdown_blocks(content):
        if kind == "heading":
            _, heading = value  # type: ignore[misc]
            if body:
                sections.append((current_title, body))
                body = []
            current_title = str(heading)
        elif kind == "table":
            rows = value  # type: ignore[assignment]
            body.extend(" · ".join(str(cell) for cell in row) for row in rows[:8])
        elif kind == "code":
            language, code = value  # type: ignore[misc]
            body.append(f"{language or 'Code'} : {str(code)[:600]}")
        else:
            body.append(_strip_inline_markdown(str(value)))
    if body or not sections:
        sections.append((current_title, body or ["Contenu de l’artefact"]))
    return sections


def export_pptx(title: str, content: str) -> bytes:
    presentation = Presentation()
    presentation.slide_width = PptxInches(13.333)
    presentation.slide_height = PptxInches(7.5)
    cover = presentation.slides.add_slide(presentation.slide_layouts[0])
    cover.shapes.title.text = title or "Artefact"
    cover.placeholders[1].text = "Créé avec Lasme LLM"
    for heading, items in _slide_sections(content):
        for start in range(0, max(len(items), 1), 6):
            slide = presentation.slides.add_slide(presentation.slide_layouts[1])
            slide.shapes.title.text = heading
            frame = slide.placeholders[1].text_frame
            frame.clear()
            for index, item in enumerate(items[start : start + 6] or [""]):
                paragraph = frame.paragraphs[0] if index == 0 else frame.add_paragraph()
                paragraph.text = item[:800]
                paragraph.font.size = PptxPt(20)
                paragraph.space_after = PptxPt(10)
    output = io.BytesIO()
    presentation.save(output)
    return output.getvalue()


def export_pdf(title: str, content: str) -> bytes:
    output = io.BytesIO()
    document = SimpleDocTemplate(
        output,
        pagesize=A4,
        rightMargin=18 * mm,
        leftMargin=18 * mm,
        topMargin=17 * mm,
        bottomMargin=17 * mm,
        title=title,
    )
    styles = getSampleStyleSheet()
    styles.add(
        ParagraphStyle(
            name="LasmeTitle",
            parent=styles["Title"],
            textColor=colors.HexColor("#102A26"),
            alignment=TA_CENTER,
            spaceAfter=14,
        )
    )
    story: List[object] = [Paragraph(html.escape(title or "Artefact"), styles["LasmeTitle"])]
    for kind, value in _markdown_blocks(content):
        if kind == "heading":
            level, text = value  # type: ignore[misc]
            story.append(Paragraph(html.escape(str(text)), styles[f"Heading{min(int(level), 3)}"]))
        elif kind in {"bullet", "number"}:
            prefix = "•" if kind == "bullet" else "–"
            story.append(Paragraph(f"{prefix} {html.escape(str(value))}", styles["BodyText"]))
        elif kind == "code":
            _, code = value  # type: ignore[misc]
            story.append(Preformatted(str(code), styles["Code"]))
        elif kind == "table":
            rows = value  # type: ignore[assignment]
            table = Table([[str(cell) for cell in row] for row in rows], repeatRows=1)
            table.setStyle(
                TableStyle(
                    [
                        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0BAE83")),
                        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                        ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#D6DEDC")),
                        ("VALIGN", (0, 0), (-1, -1), "TOP"),
                        ("FONTSIZE", (0, 0), (-1, -1), 8),
                        ("PADDING", (0, 0), (-1, -1), 5),
                    ]
                )
            )
            story.extend([Spacer(1, 6), table, Spacer(1, 8)])
        else:
            story.append(Paragraph(html.escape(_strip_inline_markdown(str(value))), styles["BodyText"]))
            story.append(Spacer(1, 5))
    document.build(story)
    return output.getvalue()


def export_csv(content: str) -> bytes:
    output = io.StringIO()
    writer = csv.writer(output, lineterminator="\r\n")
    writer.writerows(_first_table(content))
    return ("\ufeff" + output.getvalue()).encode("utf-8")


def export_html(title: str, content: str, *, raw_html: bool = False) -> bytes:
    fenced_html = re.fullmatch(
        r"\s*```html\s*\n([\s\S]*?)```\s*",
        content,
        flags=re.IGNORECASE,
    )
    if fenced_html:
        content = fenced_html.group(1)
    if raw_html and re.search(r"<(?:!doctype|html|body|main|section|div)\b", content, re.I):
        source = content
    else:
        fragments: List[str] = []
        for kind, value in _markdown_blocks(content):
            if kind == "heading":
                level, text = value  # type: ignore[misc]
                fragments.append(f"<h{min(int(level), 4)}>{html.escape(str(text))}</h{min(int(level), 4)}>")
            elif kind == "code":
                language, code = value  # type: ignore[misc]
                fragments.append(
                    f'<pre data-language="{html.escape(str(language))}"><code>{html.escape(str(code))}</code></pre>'
                )
            elif kind == "table":
                rows = value  # type: ignore[assignment]
                cells = []
                for row_index, row in enumerate(rows):
                    tag = "th" if row_index == 0 else "td"
                    cells.append("<tr>" + "".join(f"<{tag}>{html.escape(str(cell))}</{tag}>" for cell in row) + "</tr>")
                fragments.append("<div class=\"table-wrap\"><table>" + "".join(cells) + "</table></div>")
            elif kind in {"bullet", "number"}:
                fragments.append(f"<p class=\"list-item\">• {html.escape(str(value))}</p>")
            else:
                fragments.append(f"<p>{html.escape(_strip_inline_markdown(str(value)))}</p>")
        source = "\n".join(fragments)
    if re.search(r"<html\b", source, re.I):
        return source.encode("utf-8")
    document = f"""<!doctype html>
<html lang="fr">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>{html.escape(title or "Artefact")}</title>
  <style>
    :root{{--accent:#0bae83;--ink:#102a26;--muted:#5f6f6c;--line:#dbe5e2}}
    *{{box-sizing:border-box}} body{{margin:0;background:#f7faf9;color:var(--ink);font:16px/1.65 system-ui,sans-serif}}
    main{{max-width:920px;margin:48px auto;padding:48px;background:white;border:1px solid var(--line);border-radius:22px;box-shadow:0 20px 60px #1232}}
    h1,h2,h3,h4{{line-height:1.2}} h1{{font-size:2.25rem}} h2{{margin-top:2rem}}
    pre{{overflow:auto;padding:18px;border-radius:14px;background:#151820;color:#e6edf3}}
    .table-wrap{{overflow:auto}} table{{width:100%;border-collapse:collapse}} th,td{{padding:10px;border:1px solid var(--line);text-align:left}} th{{background:#e9f8f3}}
    @media(max-width:700px){{main{{margin:0;padding:24px;border:0;border-radius:0}}}}
  </style>
</head><body><main><h1>{html.escape(title or "Artefact")}</h1>{source}</main></body></html>"""
    return document.encode("utf-8")


def export_artifact(
    title: str,
    content: str,
    *,
    kind: str,
    output_format: str,
) -> Tuple[bytes, str, str]:
    format_name = output_format.lower().strip()
    if format_name not in EXPORT_FORMATS:
        raise ValueError(f"Unsupported export format: {format_name}")
    if format_name in {"md", "txt", "svg"}:
        media_type = {
            "md": "text/markdown; charset=utf-8",
            "txt": "text/plain; charset=utf-8",
            "svg": "image/svg+xml; charset=utf-8",
        }[format_name]
        return content.encode("utf-8"), media_type, safe_filename(title, format_name)
    if format_name == "html":
        payload = export_html(title, content, raw_html=kind in {"html", "interactive"})
        return payload, "text/html; charset=utf-8", safe_filename(title, "html")
    if format_name == "docx":
        return (
            export_docx(title, content),
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            safe_filename(title, "docx"),
        )
    if format_name == "xlsx":
        return (
            export_xlsx(title, content),
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            safe_filename(title, "xlsx"),
        )
    if format_name == "pptx":
        return (
            export_pptx(title, content),
            "application/vnd.openxmlformats-officedocument.presentationml.presentation",
            safe_filename(title, "pptx"),
        )
    if format_name == "pdf":
        return export_pdf(title, content), "application/pdf", safe_filename(title, "pdf")
    return export_csv(content), "text/csv; charset=utf-8", safe_filename(title, "csv")


SESSION_EXPORT_FORMATS = {"html", "md", "pdf", "json"}


def _build_session_markdown(
    session: Dict[str, Any],
    messages: Sequence[Dict[str, Any]],
) -> str:
    title = str(session.get("title") or "Conversation").strip() or "Conversation"
    created_at = str(session.get("created_at") or "")
    lines: List[str] = [f"# {title}", ""]
    if created_at:
        lines.extend([f"Date : {created_at}", ""])

    for msg in messages:
        role = str(msg.get("role") or "user").lower()
        role_label = "Utilisateur" if role == "user" else "Assistant"
        lines.append(f"## {role_label}")
        lines.append("")
        content = str(msg.get("content") or "").strip()
        if content:
            lines.append(content)
            lines.append("")
        metadata = msg.get("metadata") if isinstance(msg.get("metadata"), dict) else {}
        tool_events = metadata.get("tool_events") if isinstance(metadata, dict) else None
        if isinstance(tool_events, list) and tool_events:
            lines.append("### Outils exécutés")
            for ev in tool_events:
                if not isinstance(ev, dict):
                    continue
                t_name = str(ev.get("tool") or "outil")
                t_summary = str(ev.get("summary") or ev.get("status") or "").strip()
                lines.append(f"- {t_name} : {t_summary}")
            lines.append("")
        sources = metadata.get("sources") if isinstance(metadata, dict) else None
        if isinstance(sources, list) and sources:
            lines.append("### Sources")
            for src in sources:
                if not isinstance(src, dict):
                    continue
                s_title = str(src.get("title") or src.get("url") or "Source").strip()
                s_url = str(src.get("url") or "").strip()
                if s_url:
                    lines.append(f"- [{s_title}]({s_url})")
                else:
                    lines.append(f"- {s_title}")
            lines.append("")
    return "\n".join(lines).strip() + "\n"


def _build_session_html(
    session: Dict[str, Any],
    messages: Sequence[Dict[str, Any]],
) -> bytes:
    title = str(session.get("title") or "Conversation").strip() or "Conversation"
    created_at = str(session.get("created_at") or "")
    cards: List[str] = []

    for msg in messages:
        role = str(msg.get("role") or "user").lower()
        is_user = role == "user"
        role_label = "Utilisateur" if is_user else "Assistant Lasme"
        role_class = "msg-user" if is_user else "msg-assistant"
        content = str(msg.get("content") or "").strip()
        metadata = msg.get("metadata") if isinstance(msg.get("metadata"), dict) else {}

        body_fragments: List[str] = []
        thinking = str((metadata or {}).get("thinking") or "").strip()
        if thinking:
            body_fragments.append(
                f'<details class="thinking-box"><summary>Raisonnement</summary>'
                f'<pre>{html.escape(thinking)}</pre></details>'
            )

        tool_events = (metadata or {}).get("tool_events")
        if isinstance(tool_events, list) and tool_events:
            items: List[str] = []
            for ev in tool_events:
                if not isinstance(ev, dict):
                    continue
                t_name = html.escape(str(ev.get("tool") or "outil"))
                t_summary = html.escape(str(ev.get("summary") or ev.get("status") or ""))
                items.append(f"<li><strong>{t_name}</strong> — {t_summary}</li>")
                for gf in ev.get("generated_files") or []:
                    if isinstance(gf, dict) and str(gf.get("data_url") or "").startswith("data:image/"):
                        g_name = html.escape(str(gf.get("name") or "figure.png"))
                        g_url = html.escape(str(gf.get("data_url") or ""))
                        items.append(
                            f'<li class="tool-figure"><img src="{g_url}" alt="{g_name}" />'
                            f'<div><small>{g_name}</small></div></li>'
                        )
            if items:
                body_fragments.append(
                    f'<div class="tools-box"><strong>Outils exécutés</strong><ul>{"".join(items)}</ul></div>'
                )

        for kind, value in _markdown_blocks(content):
            if kind == "heading":
                level, text = value  # type: ignore[misc]
                lvl = min(int(level) + 1, 4)
                body_fragments.append(f"<h{lvl}>{html.escape(str(text))}</h{lvl}>")
            elif kind == "code":
                language, code = value  # type: ignore[misc]
                body_fragments.append(
                    f'<pre data-language="{html.escape(str(language))}"><code>{html.escape(str(code))}</code></pre>'
                )
            elif kind in {"bullet", "number"}:
                body_fragments.append(f'<p class="list-item">• {html.escape(str(value))}</p>')
            else:
                body_fragments.append(f"<p>{html.escape(str(value))}</p>")

        sources = (metadata or {}).get("sources")
        if isinstance(sources, list) and sources:
            src_links: List[str] = []
            for src in sources:
                if not isinstance(src, dict):
                    continue
                s_title = html.escape(str(src.get("title") or src.get("url") or "Source"))
                s_url = html.escape(str(src.get("url") or ""))
                if s_url:
                    src_links.append(f'<a href="{s_url}" target="_blank" rel="noopener">{s_title}</a>')
                else:
                    src_links.append(f"<span>{s_title}</span>")
            if src_links:
                body_fragments.append(
                    f'<div class="sources-box"><strong>Sources :</strong> {" · ".join(src_links)}</div>'
                )

        cards.append(
            f'<article class="msg-card {role_class}">'
            f'<header class="msg-role">{html.escape(role_label)}</header>'
            f'<div class="msg-body">{"".join(body_fragments)}</div>'
            f"</article>"
        )

    doc = f"""<!doctype html>
<html lang="fr">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>{html.escape(title)} — Export Lasme LLM</title>
  <style>
    :root{{--accent:#0bae83;--ink:#102a26;--muted:#5f6f6c;--line:#dbe5e2;--bg:#f5f9f7}}
    *{{box-sizing:border-box}}
    body{{margin:0;background:var(--bg);color:var(--ink);font:16px/1.65 system-ui,-apple-system,sans-serif}}
    main{{max-width:920px;margin:40px auto;padding:40px;background:#fff;border:1px solid var(--line);border-radius:22px;box-shadow:0 18px 48px rgba(16,42,38,0.08)}}
    header.doc-header{{border-bottom:1px solid var(--line);padding-bottom:18px;margin-bottom:28px}}
    header.doc-header h1{{margin:0 0 6px 0;font-size:1.9rem}}
    header.doc-header .meta{{color:var(--muted);font-size:0.9rem}}
    .msg-card{{border:1px solid var(--line);border-radius:16px;padding:18px 22px;margin-bottom:18px;background:#fff}}
    .msg-card.msg-user{{background:#f0f8f5;border-color:#bce6d8}}
    .msg-role{{font-weight:700;font-size:0.85rem;text-transform:uppercase;letter-spacing:0.04em;color:var(--accent);margin-bottom:8px}}
    .msg-user .msg-role{{color:#0b7a5c}}
    pre{{overflow:auto;padding:14px;border-radius:12px;background:#151820;color:#e6edf3;font-size:0.9rem}}
    .thinking-box,.tools-box,.sources-box{{margin:10px 0;padding:10px 14px;border-radius:10px;background:#f7faf9;border:1px solid var(--line);font-size:0.9rem}}
    .tool-figure img{{max-width:100%;border-radius:10px;margin-top:8px;border:1px solid var(--line)}}
    .sources-box a{{color:var(--accent);text-decoration:none;font-weight:500}}
  </style>
</head>
<body>
  <main>
    <header class="doc-header">
      <h1>{html.escape(title)}</h1>
      <div class="meta">Export souverain Lasme LLM · {html.escape(created_at)} · {len(messages)} message(s)</div>
    </header>
    {"".join(cards)}
  </main>
</body>
</html>"""
    return doc.encode("utf-8")


def export_session_conversation(
    session: Dict[str, Any],
    messages: Sequence[Dict[str, Any]],
    *,
    output_format: str = "html",
) -> Tuple[bytes, str, str]:
    format_name = (output_format or "html").lower().strip()
    if format_name not in SESSION_EXPORT_FORMATS:
        raise ValueError(f"Unsupported session export format: {format_name}")

    title = str(session.get("title") or "conversation").strip() or "conversation"
    if format_name == "json":
        bundle = {
            "version": 1,
            "exported_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "session": dict(session),
            "messages": [dict(m) for m in messages],
        }
        payload = json.dumps(bundle, ensure_ascii=False, indent=2).encode("utf-8")
        return payload, "application/json; charset=utf-8", safe_filename(title, "json")

    markdown_text = _build_session_markdown(session, messages)
    if format_name == "md":
        return (
            markdown_text.encode("utf-8"),
            "text/markdown; charset=utf-8",
            safe_filename(title, "md"),
        )
    if format_name == "pdf":
        return (
            export_pdf(title, markdown_text),
            "application/pdf",
            safe_filename(title, "pdf"),
        )
    return (
        _build_session_html(session, messages),
        "text/html; charset=utf-8",
        safe_filename(title, "html"),
    )
