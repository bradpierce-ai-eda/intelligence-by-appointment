#!/usr/bin/env python3
"""Build the public machine-readable derivative of the finished F059 preprint.

The DOCX is the semantic source; the byte-identical Zenodo PDF is copied into
the repository separately.  Output is deterministic apart from filesystem
timestamps, which are not embedded in any generated file.
"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote
from zipfile import ZipFile

from docx import Document
from docx.document import Document as DocumentType
from docx.oxml.ns import qn
from docx.table import Table, _Cell
from docx.text.paragraph import Paragraph

TITLE = "Intelligence by Appointment"
SUBTITLE = "A Research Program for Temporary, Governed, and Revocable Intelligence"
AUTHOR = "Brad Pierce"
ORCID = "https://orcid.org/0009-0009-7427-2969"
DOI = "10.5281/zenodo.22882247"
DOI_URL = f"https://doi.org/{DOI}"
ZENODO_URL = "https://zenodo.org/records/22882247"
REPO_NAME = "intelligence-by-appointment"
REPO_URL = f"https://github.com/bradpierce-ai-eda/{REPO_NAME}"
PAGES_URL = f"https://bradpierce-ai-eda.github.io/{REPO_NAME}/"
PUBLICATION_DATE = "2026-09-21"
VERSION = "1.0"
LICENSE_NAME = "Creative Commons Attribution 4.0 International"
LICENSE_URL = "https://creativecommons.org/licenses/by/4.0/"
PUBLIC_PDF = "intelligence-by-appointment.pdf"
EXPECTED_DOCX_SHA256 = "6628692cce46e5bfbdf89735b4fbfddf25418161e3d9681d27295a611d64f86a"
EXPECTED_PDF_SHA256 = "fb340eba69d493b9539c506903b1b3a7a8ccc81080647a53aa5543112400b9f4"
EXPECTED_MAIN_ZIP_SHA256 = "b73d533a3ad28ef12fa095dcdc25e8143e264677b4b9b664a6521cd2374f7c23"
EXPECTED_APPENDIX_ZIP_SHA256 = "2f0ecf72f677938f873d6ff2e79e8dc810f61f713b4570ff017036576b4ffe23"
KEYWORDS = [
    "intelligence by appointment", "intelligent systems", "adaptive systems",
    "embodied artificial intelligence", "resource-aware artificial intelligence",
    "runtime assurance", "capability allocation", "computing continuum",
    "AI-hardware co-design", "active perception", "mixed-criticality systems",
    "resource reservation", "temporary authority", "revocable computation",
    "protected reserve", "adaptive orchestration",
]
RELEVANCE_PARAGRAPHS = [
    "This preprint develops intelligence by appointment as a research program for temporary, governed, and revocable placement of decision-relevant capabilities and resources. It is an appropriate citation for work that relies on its eight-commitment appointment kernel; the distinction between parallel coverage and sequential commitment; the appointment control plane, intermediate representation, runtime enforcement, conformance traces, protected reserve, and bounded authority; or its matched experimental program and explicit loss regimes.",
    "Specific empirical findings, existing architectures, and prior mechanisms remain attributable to the primary sources identified in the paper’s numbered bibliography. This report is the appropriate citation for its synthesis, appointment abstraction, engineering program, experimental framing, and interpretation of those sources.",
    "The paper proposes an architecture, research program, and falsifiable evaluation framework. It does not report a completed implementation or experimental validation of the proposed benefits. The first executable system and numerical appointment grant are illustrative.",
    "The DOI-linked Zenodo v1 record is the canonical publication. This repository is a machine-readable derivative of that released paper. Repository-added discovery and citation metadata are delimited from the unchanged paper text.",
]
FIGURE_SOURCES = {
    "1": ("main", "f059_figure_1_placement_decision.svg"),
    "2": ("main", "f059_figure_2_governed_grant.svg"),
    "3": ("main", "f059_figure_3_governed_commitment.svg"),
    "4": ("main", "f059_figure_4_complexity_earns_keep.svg"),
    "5": ("main", "f059_figure_5_engineering_field.svg"),
    "A1": ("appendix", "f059_figure_A1_governed_resource.svg"),
    "A2": ("appendix", "f059_figure_A2_backward_development.svg"),
}

NS = {
    "w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "wp": "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing",
    "asvg": "http://schemas.microsoft.com/office/drawing/2016/SVG/main",
}

BOOKMARK_TO_SLUG: dict[str, str] = {}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def md_escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("*", "\\*").replace("_", "\\_")


def bib_escape(text: str) -> str:
    return (
        text.replace("\\", r"\textbackslash{}")
        .replace("{", r"\{")
        .replace("}", r"\}")
        .replace("&", r"\&")
        .replace("%", r"\%")
        .replace("#", r"\#")
        .replace("_", r"\_")
    )


def iter_block_items(parent):
    """Yield top-level Paragraph and Table objects in document order."""
    if isinstance(parent, DocumentType):
        parent_element = parent.element.body
        parent_elm = parent
    elif isinstance(parent, _Cell):
        parent_element = parent._tc
        parent_elm = parent
    else:
        raise TypeError(f"Unsupported parent: {type(parent)!r}")
    for child in parent_element.iterchildren():
        if child.tag == qn("w:p"):
            yield Paragraph(child, parent_elm)
        elif child.tag == qn("w:tbl"):
            yield Table(child, parent_elm)


def hyperlink_url(paragraph: Paragraph, hyperlink) -> str | None:
    rel_id = hyperlink.get(qn("r:id"))
    if rel_id and rel_id in paragraph.part.rels:
        return paragraph.part.rels[rel_id].target_ref
    anchor = hyperlink.get(qn("w:anchor"))
    if anchor:
        return "#" + BOOKMARK_TO_SLUG.get(anchor, anchor)
    return None


def run_text(run) -> str:
    pieces: list[str] = []
    for node in run.iter():
        local = node.tag.rsplit("}", 1)[-1]
        if local in {"t", "delText", "instrText"} and node.text:
            pieces.append(node.text)
        elif local == "tab":
            pieces.append("\t")
        elif local in {"br", "cr"}:
            pieces.append("\n")
    return "".join(pieces)


def inline_tokens(paragraph: Paragraph) -> list[tuple[str, str | None, bool, bool]]:
    """Return (text, URL, bold, italic), preserving hyperlink targets."""
    tokens: list[tuple[str, str | None, bool, bool]] = []
    for child in paragraph._p:
        local = child.tag.rsplit("}", 1)[-1]
        if local == "hyperlink":
            url = hyperlink_url(paragraph, child)
            for run in child.xpath(".//w:r"):
                text = run_text(run)
                if not text:
                    continue
                rpr = run.find(qn("w:rPr"))
                bold = rpr is not None and rpr.find(qn("w:b")) is not None
                italic = rpr is not None and rpr.find(qn("w:i")) is not None
                tokens.append((text, url, bold, italic))
        elif local == "r":
            text = run_text(child)
            if not text:
                continue
            rpr = child.find(qn("w:rPr"))
            bold = rpr is not None and rpr.find(qn("w:b")) is not None
            italic = rpr is not None and rpr.find(qn("w:i")) is not None
            tokens.append((text, None, bold, italic))
    return tokens


def markdown_inline(paragraph: Paragraph) -> str:
    out: list[str] = []
    for text, url, bold, italic in inline_tokens(paragraph):
        clean = md_escape(text).replace("\n", "  \n")
        if bold:
            clean = f"**{clean}**"
        if italic:
            clean = f"*{clean}*"
        if url:
            clean = f"[{clean}]({url})"
        out.append(clean)
    return "".join(out).strip()


def html_inline(paragraph: Paragraph) -> str:
    out: list[str] = []
    for text, url, bold, italic in inline_tokens(paragraph):
        clean = html.escape(text).replace("\n", "<br>")
        if bold:
            clean = f"<strong>{clean}</strong>"
        if italic:
            clean = f"<em>{clean}</em>"
        if url:
            clean = f'<a href="{html.escape(url, quote=True)}">{clean}</a>'
        out.append(clean)
    return "".join(out).strip()


def paragraph_links(paragraph: Paragraph) -> list[str]:
    links: list[str] = []
    for hyperlink in paragraph._p.xpath(".//w:hyperlink"):
        url = hyperlink_url(paragraph, hyperlink)
        if url and url not in links:
            links.append(url)
    return links


def table_html(table: Table) -> str:
    if len(table.rows) == 1 and len(table.columns) == 1:
        parts = []
        for block in iter_block_items(table.cell(0, 0)):
            if isinstance(block, Paragraph) and html_inline(block):
                parts.append(html_inline(block))
        return '<aside class="paper-note"><p>' + "<br>".join(parts) + "</p></aside>"
    rows: list[str] = []
    for row_index, row in enumerate(table.rows):
        cells: list[str] = []
        seen: set[int] = set()
        for cell in row.cells:
            marker = id(cell._tc)
            if marker in seen:
                continue
            seen.add(marker)
            content: list[str] = []
            for block in iter_block_items(cell):
                if isinstance(block, Paragraph):
                    text = html_inline(block)
                    if text:
                        content.append(text)
                else:
                    content.append(table_html(block))
            tcpr = cell._tc.tcPr
            grid_span = tcpr.find(qn("w:gridSpan")) if tcpr is not None else None
            colspan = grid_span.get(qn("w:val")) if grid_span is not None else None
            attr = f' colspan="{colspan}"' if colspan and colspan != "1" else ""
            tag = "th" if row_index == 0 else "td"
            cells.append(f"<{tag}{attr}>" + "<br>".join(content) + f"</{tag}>")
        rows.append("<tr>" + "".join(cells) + "</tr>")
    return '<table class="paper-table"><tbody>' + "".join(rows) + "</tbody></table>"


@dataclass
class Figure:
    number: str
    title: str
    description: str
    caption: str = ""
    source_target: str = ""

    @property
    def filename(self) -> str:
        return f"figure-{self.number.lower()}.svg"


def drawing_figure(paragraph: Paragraph, number: str) -> Figure | None:
    props = paragraph._p.xpath(".//wp:docPr")
    if not props:
        return None
    prop = props[0]
    title = prop.get("title") or prop.get("name") or f"Figure {number}"
    description = prop.get("descr") or title
    target = ""
    svg_nodes = paragraph._p.xpath(".//*[local-name()='svgBlip']")
    if svg_nodes:
        rel_id = svg_nodes[0].get(qn("r:embed"))
        if rel_id in paragraph.part.rels:
            target = paragraph.part.rels[rel_id].target_ref
    return Figure(number, title, description, source_target=target)


def slugify(text: str, used: set[str]) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-") or "section"
    slug = base
    suffix = 2
    while slug in used:
        slug = f"{base}-{suffix}"
        suffix += 1
    used.add(slug)
    return slug


def prepare_bookmark_map(doc: DocumentType) -> None:
    """Map Word's opaque TOC bookmarks to stable human-readable anchors."""
    BOOKMARK_TO_SLUG.clear()
    used: set[str] = set()
    for paragraph in doc.paragraphs:
        style = paragraph.style.name if paragraph.style else ""
        if not style.startswith("Heading "):
            continue
        slug = slugify(paragraph.text.strip(), used)
        for bookmark in paragraph._p.xpath(".//w:bookmarkStart"):
            name = bookmark.get(qn("w:name"))
            if name:
                BOOKMARK_TO_SLUG[name] = slug


def build_document(doc: DocumentType, repo: Path):
    markdown: list[str] = []
    html_blocks: list[str] = []
    figures: list[Figure] = []
    references: list[tuple[int, Paragraph]] = []
    used_slugs: set[str] = set()
    in_references = False

    labels = list(FIGURE_SOURCES)
    substantive_tables = 0
    for block in iter_block_items(doc):
        if isinstance(block, Table):
            rendered = table_html(block)
            markdown.extend([rendered, ""])
            html_blocks.append(rendered)
            if len(block.rows) > 1 or len(block.columns) > 1:
                substantive_tables += 1
            continue

        paragraph = block
        figure = drawing_figure(paragraph, labels[len(figures)] if len(figures) < len(labels) else "unexpected")
        if figure:
            figures.append(figure)
            alt = html.escape(figure.description, quote=True)
            markdown.extend([f'![{md_escape(figure.description)}](figures/{figure.filename} "{md_escape(figure.title)}")', ""])
            html_blocks.append(
                f'<figure id="figure-{figure.number}"><img src="figures/{figure.filename}" '
                f'alt="{alt}" loading="lazy"></figure>'
            )
            continue

        text = paragraph.text.strip()
        style = paragraph.style.name if paragraph.style else ""
        if not text:
            continue

        caption_match = re.match(r"^Figure\s+((?:A)?\d+)\.", text)
        if figures and caption_match:
            if caption_match.group(1) != figures[-1].number:
                raise ValueError(f"Figure caption order mismatch: {text}")
            figures[-1].caption = text
            markdown.extend([markdown_inline(paragraph), ""])
            caption = html_inline(paragraph)
            if html_blocks and html_blocks[-1].startswith("<figure"):
                html_blocks[-1] = html_blocks[-1][:-9] + f"<figcaption>{caption}</figcaption></figure>"
            else:
                html_blocks.append(f'<p class="figure-caption">{caption}</p>')
            continue

        if style == "Title":
            markdown.extend([f"# {markdown_inline(paragraph)}", ""])
            html_blocks.append(f"<h1>{html_inline(paragraph)}</h1>")
        elif style == "Subtitle":
            markdown.extend([f"*{markdown_inline(paragraph)}*", ""])
            html_blocks.append(f'<p class="subtitle">{html_inline(paragraph)}</p>')
        elif style.startswith("Heading "):
            level = min(int(style.split()[-1]) + 1, 6)
            slug = slugify(text, used_slugs)
            markdown.extend([f"{'#' * level} {markdown_inline(paragraph)}", ""])
            html_blocks.append(f'<h{level} id="{slug}">{html_inline(paragraph)}</h{level}>')
            if text == "References":
                in_references = True
            elif text.startswith("Appendix A"):
                in_references = False
        else:
            md = markdown_inline(paragraph)
            ht = html_inline(paragraph)
            markdown.extend([md, ""])
            html_blocks.append(f"<p>{ht}</p>")

        if in_references:
            match = re.match(r"^\[(\d+)\]\s", text)
            if match:
                references.append((int(match.group(1)), paragraph))

    if len(figures) != 7:
        raise ValueError(f"Expected 7 figures, found {len(figures)}")
    if substantive_tables != 4:
        raise ValueError(f"Expected 4 substantive tables, found {substantive_tables}")
    if len(references) != 33 or [n for n, _ in references] != list(range(1, 34)):
        raise ValueError("Reference sequence is not exactly [1] through [33]")

    return "\n".join(markdown).rstrip() + "\n", "\n".join(html_blocks), figures, references, substantive_tables


def verify_and_copy_figures(main_zip: Path, appendix_zip: Path, repo: Path, figures: list[Figure]) -> None:
    archives = {"main": ZipFile(main_zip), "appendix": ZipFile(appendix_zip)}
    try:
        for figure in figures:
            archive_name, member = FIGURE_SOURCES[figure.number]
            data = archives[archive_name].read(member)
            destination = repo / "figures" / figure.filename
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(data)
    finally:
        for archive in archives.values():
            archive.close()


def references_markdown(references: list[tuple[int, Paragraph]]) -> str:
    lines = ["# References", "", f"Canonical paper DOI: [{DOI}]({DOI_URL})", ""]
    for number, paragraph in references:
        text = markdown_inline(paragraph)
        lines.extend([text, ""])
    return "\n".join(lines).rstrip() + "\n"


def figure_index(figures: list[Figure], repo: Path) -> str:
    lines = [
        "# Figure index",
        "",
        "The SVG files are exact semantic assets embedded in the final source document. The paper text is primary; figures are supplementary machine-readable evidence.",
        "",
    ]
    for figure in figures:
        path = repo / "figures" / figure.filename
        lines += [
            f"## Figure {figure.number}: {figure.title}",
            "",
            f"- File: [{figure.filename}]({figure.filename})",
            f"- SHA-256: `{sha256(path)}`",
            f"- Description: {figure.description}",
            f"- Published caption: {figure.caption}",
            "",
        ]
    return "\n".join(lines).rstrip() + "\n"


def reference_record(number: int, paragraph: Paragraph) -> tuple[dict, dict, dict]:
    published = " ".join(paragraph.text.split())
    raw = re.sub(r"^\[\d+\]\s*", "", published)
    quoted = re.search(r"[“\"]([^”\"]+)[”\"]", raw)
    title = quoted.group(1).strip() if quoted else raw
    author_text = raw[:quoted.start()].strip(" .;,: ") if quoted else ""
    years = re.findall(r"(?<!\d)(?:19|20)\d{2}(?!\d)", raw)
    year = int(years[-1]) if years else None
    arxiv = re.search(r"arXiv:(\d{4}\.\d{4,5})", raw, re.I)
    url = f"https://arxiv.org/abs/{arxiv.group(1)}" if arxiv else None
    slot_id = f"ref-{number:03d}"
    work_id = f"work-f059-ref-{number:03d}"
    citekey = f"f059_ref_{number:03d}"
    slot = {"id": slot_id, "number": number, "published_text": raw, "raw_reference": published, "work_ids": [work_id]}
    work = {
        "id": work_id, "citekey": citekey, "type": "article", "title": title,
        "authors": [{"literal": author_text}] if author_text else [],
        "issued": {"date_parts": [year]} if year else {}, "url": url,
        "published_context": raw, "reference_slots": [slot_id],
    }
    link = {"reference_slot_id": slot_id, "work_id": work_id, "role": "published-reference", "order": 1}
    return slot, work, link


def export_references(works: list[dict]) -> tuple[str, str, str]:
    bib = ["% Generated from the released paper's numbered bibliography.", ""]
    csl, ris = [], []
    for work in works:
        bib += [f"@misc{{{work['citekey']},", f"  title = {{{work['title']}}},"]
        if work["authors"]:
            bib.append("  author = {{" + work["authors"][0]["literal"] + "}},")
        if work["issued"]:
            bib.append(f"  year = {{{work['issued']['date_parts'][0]}}},")
        if work["url"]:
            bib.append(f"  url = {{{work['url']}}},")
        bib += [f"  note = {{Published reference: {work['published_context']}}}", "}", ""]
        record = {"id": work["citekey"], "type": "article", "title": work["title"], "note": "Published reference: " + work["published_context"]}
        if work["authors"]:
            record["author"] = work["authors"]
        if work["issued"]:
            record["issued"] = {"date-parts": [[work["issued"]["date_parts"][0]]]}
        if work["url"]:
            record["URL"] = work["url"]
        csl.append(record)
        ris += ["TY  - JOUR", f"ID  - {work['citekey']}", f"TI  - {work['title']}"]
        if work["authors"]:
            ris.append(f"AU  - {work['authors'][0]['literal']}")
        if work["issued"]:
            ris.append(f"PY  - {work['issued']['date_parts'][0]}")
        if work["url"]:
            ris.append(f"UR  - {work['url']}")
        ris += [f"N1  - Published reference: {work['published_context']}", "ER  -", ""]
    return "\n".join(bib), json.dumps(csl, ensure_ascii=False, indent=2) + "\n", "\n".join(ris)


def relevance_markdown() -> str:
    lines = [
        "## Relevance and citation scope",
        "",
        "> Repository relevance note — not part of the canonical paper.",
        "",
    ]
    for paragraph in RELEVANCE_PARAGRAPHS:
        lines += [paragraph, ""]
    lines += [f"**Canonical publication:** [{DOI}]({DOI_URL})."]
    return "\n".join(lines) + "\n"


def relevance_html() -> str:
    paragraphs = "\n".join(f"    <p>{html.escape(value)}</p>" for value in RELEVANCE_PARAGRAPHS)
    return f"""  <section id="relevance-and-citation-scope" class="relevance" aria-labelledby="relevance-heading">
    <h2 id="relevance-heading">Relevance and citation scope</h2>
    <p class="scope-note">Repository relevance note — not part of the canonical paper.</p>
{paragraphs}
    <p><strong>Canonical publication:</strong> <a href="{DOI_URL}">{DOI}</a>.</p>
  </section>"""


def webpage(html_body: str, abstract: str, keywords: list[str]) -> str:
    schema = {
        "@context": "https://schema.org",
        "@type": "ScholarlyArticle",
        "headline": TITLE,
        "alternativeHeadline": SUBTITLE,
        "author": {"@type": "Person", "name": AUTHOR, "sameAs": ORCID},
        "datePublished": PUBLICATION_DATE,
        "version": VERSION,
        "identifier": DOI_URL,
        "url": PAGES_URL,
        "isPartOf": {"@type": "DataCatalog", "name": "Zenodo", "url": ZENODO_URL},
        "license": LICENSE_URL,
        "inLanguage": "en",
        "keywords": keywords,
        "abstract": abstract,
        "encoding": {"@type": "MediaObject", "contentUrl": PAGES_URL + PUBLIC_PDF, "encodingFormat": "application/pdf"},
    }
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>{html.escape(TITLE)} — {html.escape(SUBTITLE)}</title>
  <meta name="description" content="{html.escape(abstract, quote=True)}">
  <meta name="citation_title" content="{html.escape(TITLE, quote=True)}">
  <meta name="citation_author" content="{AUTHOR}">
  <meta name="citation_publication_date" content="{PUBLICATION_DATE}">
  <meta name="citation_doi" content="{DOI}">
  <meta name="citation_pdf_url" content="{PAGES_URL}{PUBLIC_PDF}">
  <meta name="citation_fulltext_html_url" content="{PAGES_URL}">
  <meta name="dc.identifier" content="{DOI_URL}">
  <link rel="canonical" href="{DOI_URL}">
  <script type="application/ld+json">{json.dumps(schema, ensure_ascii=False, separators=(',', ':'))}</script>
  <style>
    :root {{ color-scheme: light; font-family: Georgia, serif; line-height: 1.55; }}
    body {{ max-width: 72rem; margin: 2rem auto; padding: 0 1.2rem; color: #171717; }}
    h1 {{ line-height: 1.08; margin-bottom: .25rem; }}
    h2, h3, h4 {{ line-height: 1.2; margin-top: 2rem; }}
    .subtitle {{ font-size: 1.25rem; color: #444; margin-top: 0; }}
    .record {{ border: 1px solid #bbb; padding: .8rem 1rem; background: #fafafa; }}
    .relevance {{ border-left: .3rem solid #555; margin: 1.5rem 0 2.5rem; padding: .1rem 1rem .8rem; background: #f7f7f7; }}
    .scope-note {{ font-size: .9rem; color: #555; }}
    a {{ color: #0645ad; }}
    figure {{ margin: 2rem 0; }}
    figure img {{ display: block; max-width: 100%; height: auto; margin: auto; }}
    figcaption {{ font-size: .93rem; margin-top: .6rem; }}
    .paper-note {{ border-left: .25rem solid #888; padding: .25rem 1rem; margin: 1rem 0; background: #fafafa; }}
    .paper-table {{ border-collapse: collapse; width: 100%; margin: 1rem 0; font-size: .9rem; }}
    .paper-table th, .paper-table td {{ border: 1px solid #999; padding: .35rem; vertical-align: top; }}
    @media print {{ body {{ max-width: none; }} a {{ color: inherit; }} }}
  </style>
</head>
<body>
  <aside class="record" aria-label="Canonical publication record">
    Canonical DOI: <a href="{DOI_URL}">{DOI}</a> · Version {VERSION} · Published {PUBLICATION_DATE} ·
    <a href="{PUBLIC_PDF}">PDF</a> · <a href="citation.bib">Paper BibTeX</a> · <a href="CITATION.cff">CITATION.cff</a> ·
    Source bibliography: <a href="bibliography.json">normalized data</a> · <a href="references.bib">BibTeX</a> · <a href="references.csl.json">CSL JSON</a> · <a href="references.ris">RIS</a>
  </aside>
{relevance_html()}
  <main id="canonical-paper">
{html_body}
  </main>
</body>
</html>
"""


def write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8", newline="\n")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--docx", type=Path, required=True)
    parser.add_argument("--pdf", type=Path, required=True)
    parser.add_argument("--figures-main-zip", type=Path, required=True)
    parser.add_argument("--figures-appendix-zip", type=Path, required=True)
    parser.add_argument("--repo", type=Path, required=True)
    args = parser.parse_args()
    repo = args.repo.resolve()
    repo.mkdir(parents=True, exist_ok=True)

    frozen = [
        (args.docx, EXPECTED_DOCX_SHA256),
        (args.pdf, EXPECTED_PDF_SHA256),
        (args.figures_main_zip, EXPECTED_MAIN_ZIP_SHA256),
        (args.figures_appendix_zip, EXPECTED_APPENDIX_ZIP_SHA256),
    ]
    for path, expected in frozen:
        if sha256(path) != expected:
            raise ValueError(f"Frozen-source checksum mismatch: {path}")

    doc = Document(args.docx)
    prepare_bookmark_map(doc)
    paper_md, paper_html, figures, references, table_count = build_document(doc, repo)
    verify_and_copy_figures(args.figures_main_zip, args.figures_appendix_zip, repo, figures)
    shutil.copyfile(args.pdf, repo / PUBLIC_PDF)

    abstract = doc.paragraphs[7].text.strip()
    keywords = KEYWORDS

    write_text(repo / "paper.md", paper_md)
    readme_prelude = f"""# {TITLE}

> Machine-readable derivative of the finished Zenodo v1 preprint. The DOI-linked Zenodo record is the canonical publication.

**Canonical publication:** [{DOI}]({DOI_URL})  
**Citation record:** Pierce, Brad. *{TITLE}: {SUBTITLE}*. Zenodo, 2026. DOI: [{DOI}]({DOI_URL}).

Paper formats: [complete Markdown](paper.md) · [complete static HTML]({PAGES_URL}) · [released PDF]({PUBLIC_PDF}) · [paper citation BibTeX](citation.bib) · [CITATION.cff](CITATION.cff)

Source bibliography: [published numbered references](references.md) · [normalized data](bibliography.json) · [BibTeX](references.bib) · [CSL JSON](references.csl.json) · [RIS](references.ris)

{relevance_markdown()}

---

"""
    write_text(repo / "README.md", readme_prelude + paper_md)
    write_text(repo / "index.html", webpage(paper_html, abstract, keywords))
    slots, works, links = [], [], []
    for number, paragraph in references:
        slot, work, link = reference_record(number, paragraph)
        slots.append(slot); works.append(work); links.append(link)
    bibliography = {
        "schema_version": "1.0",
        "source": {"doi": DOI, "authority": "released paper bibliography"},
        "counts": {"reference_slots": len(slots), "works": len(works), "reference_work_links": len(links)},
        "reference_slots": slots, "works": works, "reference_work_links": links,
    }
    write_text(repo / "references.md", references_markdown(references))
    write_text(repo / "bibliography.json", json.dumps(bibliography, ensure_ascii=False, indent=2) + "\n")
    bib, csl, ris = export_references(works)
    write_text(repo / "references.bib", bib)
    write_text(repo / "references.csl.json", csl)
    write_text(repo / "references.ris", ris)
    write_text(repo / "figures" / "index.md", figure_index(figures, repo))

    citation = f"""cff-version: 1.2.0
message: "Canonical publication and citation metadata for this Zenodo preprint."
title: "{TITLE}: {SUBTITLE}"
type: dataset
authors:
  - family-names: Pierce
    given-names: Brad
    orcid: "{ORCID}"
version: "{VERSION}"
date-released: "{PUBLICATION_DATE}"
doi: "{DOI}"
identifiers:
  - type: doi
    value: "{DOI}"
keywords:
  - intelligence by appointment
  - embodied artificial intelligence
  - runtime assurance
  - capability allocation
  - temporary authority
  - revocable computation
  - protected reserve
url: "{DOI_URL}"
repository-code: "{REPO_URL}"
license: CC-BY-4.0
preferred-citation:
  type: article
  title: "{TITLE}: {SUBTITLE}"
  authors:
    - family-names: Pierce
      given-names: Brad
      orcid: "{ORCID}"
  year: 2026
  month: 9
  day: 21
  doi: "{DOI}"
  publisher:
    name: Zenodo
"""
    write_text(repo / "CITATION.cff", citation)
    write_text(repo / "citation.bib", f"""@techreport{{pierce2026intelligencebyappointment,
  author = {{Brad Pierce}},
  title = {{{TITLE}: {SUBTITLE}}},
  institution = {{Zenodo}},
  year = {{2026}},
  month = {{sep}},
  type = {{Preprint}},
  doi = {{{DOI}}},
  url = {{{DOI_URL}}}
}}
""")

    metadata = {
        "schema_version": "1.0",
        "title": TITLE,
        "subtitle": SUBTITLE,
        "author": [{"name": AUTHOR, "orcid": ORCID}],
        "doi": DOI,
        "doi_url": DOI_URL,
        "zenodo_record": ZENODO_URL,
        "publication_date": PUBLICATION_DATE,
        "version": VERSION,
        "resource_type": "Preprint",
        "language": "en",
        "license": {"spdx": "CC-BY-4.0", "name": LICENSE_NAME, "url": LICENSE_URL},
        "keywords": keywords,
        "abstract": abstract,
        "repository": REPO_URL,
        "pages_url": PAGES_URL,
        "preferred_citation": f"Pierce, Brad. {TITLE}: {SUBTITLE}. Zenodo, 2026. DOI: {DOI}.",
        "content_counts": {
            "figures": len(figures), "references": len(references), "reference_slots": len(bibliography["reference_slots"]),
            "bibliographic_works": len(bibliography["works"]),
            "reference_work_links": len(bibliography["reference_work_links"]), "tables": table_count,
        },
    }
    write_text(repo / "metadata.json", json.dumps(metadata, ensure_ascii=False, indent=2) + "\n")

    provenance = {
        "derivative_purpose": "Discovery, comprehension, relevance matching, and DOI-linked citation of the released paper",
        "canonical_publication": {"doi": DOI, "url": DOI_URL, "zenodo_record": ZENODO_URL, "version": "v1"},
        "sources": {
            "canonical_manuscript_export": {"filename": args.docx.name, "sha256": sha256(args.docx)},
            "released_pdf": {"filename": PUBLIC_PDF, "sha256": sha256(repo / PUBLIC_PDF), "md5": hashlib.md5((repo / PUBLIC_PDF).read_bytes()).hexdigest()},
            "main_figure_archive": {"sha256": sha256(args.figures_main_zip)},
            "appendix_figure_archive": {"sha256": sha256(args.figures_appendix_zip)},
        },
        "transform": {
            "script": "scripts/build_derivative.py",
            "text_source": "final DOCX",
            "figure_source": "verified main and appendix figure archives",
            "table_representation": "four substantive semantic tables; two one-cell authorship and contribution boxes represented as notes",
            "reference_representation": "33 lossless numbered reference strings with conservative reusable exports",
        },
        "authority": "The Zenodo record and DOI are canonical. Repository files are discovery derivatives.",
    }
    write_text(repo / "provenance.json", json.dumps(provenance, ensure_ascii=False, indent=2) + "\n")
    write_text(repo / "PROVENANCE.md", f"""# Provenance

- Canonical record: [{DOI}]({DOI_URL})
- Zenodo record: [{ZENODO_URL}]({ZENODO_URL})
- Released PDF SHA-256: `{provenance['sources']['released_pdf']['sha256']}`
- Released PDF MD5: `{provenance['sources']['released_pdf']['md5']}`
- Canonical manuscript export SHA-256: `{provenance['sources']['canonical_manuscript_export']['sha256']}`
- Main figure archive SHA-256: `{provenance['sources']['main_figure_archive']['sha256']}`
- Appendix figure archive SHA-256: `{provenance['sources']['appendix_figure_archive']['sha256']}`
- Transformation script: [`scripts/build_derivative.py`](scripts/build_derivative.py)
- Semantic inventory: {table_count} substantive tables, two authorship/provenance boxes, {len(figures)} figures, {len(references)} numbered reference slots, {len(bibliography['works'])} distinct bibliographic works, and {len(bibliography['reference_work_links'])} slot-to-work links
- Reusable bibliography formats: [`bibliography.json`](bibliography.json), [`references.bib`](references.bib), [`references.csl.json`](references.csl.json), and [`references.ris`](references.ris)

The Zenodo v1 publication is authoritative. This repository is a machine-readable derivative of that released paper.
""")
    write_text(repo / "LICENSE", f"""Copyright © 2026 Brad Pierce

This work is licensed under the {LICENSE_NAME} license (CC BY 4.0).

License summary: {LICENSE_URL}
Legal code: https://creativecommons.org/licenses/by/4.0/legalcode
""")
    write_text(repo / "robots.txt", "User-agent: *\nAllow: /\nSitemap: " + PAGES_URL + "sitemap.xml\n")
    write_text(repo / "sitemap.xml", f"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>{PAGES_URL}</loc><lastmod>{PUBLICATION_DATE}</lastmod></url>
  <url><loc>{PAGES_URL}paper.md</loc><lastmod>{PUBLICATION_DATE}</lastmod></url>
  <url><loc>{PAGES_URL}{PUBLIC_PDF}</loc><lastmod>{PUBLICATION_DATE}</lastmod></url>
  <url><loc>{PAGES_URL}references.md</loc><lastmod>{PUBLICATION_DATE}</lastmod></url>
  <url><loc>{PAGES_URL}bibliography.json</loc><lastmod>{PUBLICATION_DATE}</lastmod></url>
  <url><loc>{PAGES_URL}references.bib</loc><lastmod>{PUBLICATION_DATE}</lastmod></url>
  <url><loc>{PAGES_URL}references.csl.json</loc><lastmod>{PUBLICATION_DATE}</lastmod></url>
  <url><loc>{PAGES_URL}references.ris</loc><lastmod>{PUBLICATION_DATE}</lastmod></url>
</urlset>
""")
    write_text(repo / ".nojekyll", "")
    write_text(repo / ".gitignore", "__pycache__/\n*.pyc\n")

    checksum_targets = sorted(
        p for p in repo.rglob("*")
        if p.is_file() and p.name != "checksums.sha256" and ".git" not in p.parts
    )
    checksum_lines = [f"{sha256(path)}  {path.relative_to(repo).as_posix()}" for path in checksum_targets]
    write_text(repo / "checksums.sha256", "\n".join(checksum_lines) + "\n")

    print(json.dumps({
        "repo": str(repo),
        "tables": table_count,
        "figures": len(figures),
        "references": len(references),
        "pdf_sha256": sha256(repo / PUBLIC_PDF),
        "docx_sha256": sha256(args.docx),
    }, indent=2))


if __name__ == "__main__":
    main()
