#!/usr/bin/env python3
"""Fail-closed validation for the F059 public paper derivative."""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml
from lxml import etree, html
from pypdf import PdfReader


DOI = "10.5281/zenodo.22882247"
PDF_NAME = "intelligence-by-appointment.pdf"
PDF_SHA256 = "fb340eba69d493b9539c506903b1b3a7a8ccc81080647a53aa5543112400b9f4"
PAPER_MD_SHA256 = "17d6442db69c878fb896cab99c4cdff5805d96a43695d8d1d616c048a5768808"
EXPECTED_FIGURES = 7
EXPECTED_TABLES = 4
EXPECTED_REFERENCES = 33
EXPECTED_PAGES = 50


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def normalized_scope_from_readme(readme: str) -> str:
    value = readme.split("## Relevance and citation scope", 1)[1].split("\n---\n", 1)[0]
    value = "Relevance and citation scope" + value
    value = re.sub(r"\[([^]]+)\]\([^)]+\)", r"\1", value)
    value = re.sub(r"(?m)^\s*[#>`-]+\s*", "", value).replace("*", "")
    return " ".join(value.split())


def main() -> None:
    root = Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()
    required = {
        ".gitignore", ".nojekyll", "CITATION.cff", "LICENSE", "PROVENANCE.md",
        "README.md", "bibliography.json", "checksums.sha256", "citation.bib",
        "index.html", "metadata.json", "paper.md", PDF_NAME, "provenance.json",
        "references.bib", "references.csl.json", "references.md", "references.ris",
        "robots.txt", "sitemap.xml", "figures/index.md",
        "scripts/build_derivative.py", "scripts/validate_derivative.py",
    }
    existing = {p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file() and ".git" not in p.parts}
    require(required <= existing, f"Missing required files: {sorted(required - existing)}")

    require(digest(root / PDF_NAME) == PDF_SHA256, "Released PDF hash mismatch")
    require(digest(root / "paper.md") == PAPER_MD_SHA256, "Canonical Markdown paper body changed")
    require(len(PdfReader(root / PDF_NAME).pages) == EXPECTED_PAGES, "PDF page-count mismatch")

    metadata = json.loads((root / "metadata.json").read_text(encoding="utf-8"))
    provenance = json.loads((root / "provenance.json").read_text(encoding="utf-8"))
    cff = yaml.safe_load((root / "CITATION.cff").read_text(encoding="utf-8"))
    require(metadata["doi"] == DOI and provenance["canonical_publication"]["doi"] == DOI and cff["doi"] == DOI, "DOI metadata mismatch")
    require(metadata["license"]["spdx"] == "CC-BY-4.0" and cff["license"] == "CC-BY-4.0", "License mismatch")
    require(metadata["content_counts"] == {"figures": 7, "references": 33, "reference_slots": 33, "bibliographic_works": 33, "reference_work_links": 33, "tables": 4}, "Content inventory mismatch")
    require(provenance["sources"]["released_pdf"]["sha256"] == PDF_SHA256, "Provenance PDF mismatch")
    require(provenance["sources"]["released_pdf"]["md5"] == "fcd4b18076cf73aa8cf8600bfb3e6c31", "Provenance MD5 mismatch")

    readme = (root / "README.md").read_text(encoding="utf-8")
    paper_md = (root / "paper.md").read_text(encoding="utf-8")
    index_source = (root / "index.html").read_text(encoding="utf-8")
    page = html.fromstring(index_source.encode("utf-8"))
    require(readme.count("## Relevance and citation scope") == 1, "README relevance section missing or duplicated")
    require("Relevance and citation scope" not in paper_md, "Repository relevance note leaked into canonical paper body")
    require(readme.index("## Relevance and citation scope") < 2500, "README relevance section appears too late")
    sections = page.xpath('//section[@id="relevance-and-citation-scope"]')
    require(len(sections) == 1, "HTML relevance section missing or duplicated")
    require(index_source.index('id="scholarly-front-matter"') < index_source.index('id="relevance-and-citation-scope"') < index_source.index('<main id="canonical-paper">'), "Scholarly front matter, relevance scope, and canonical paper are out of order")
    html_scope = " ".join(sections[0].text_content().split())
    require(normalized_scope_from_readme(readme) == html_scope, "README and HTML relevance wording drifted")
    for phrase in [
        "eight-commitment appointment kernel", "parallel coverage and sequential commitment",
        "matched experimental program and explicit loss regimes", "does not report a completed implementation",
        "first executable system and numerical appointment grant are illustrative",
        "DOI-linked Zenodo v1 record is the canonical publication",
    ]:
        require(phrase in html_scope, f"Required relevance boundary missing: {phrase}")

    require(page.xpath('//meta[@name="citation_doi"]/@content') == [DOI], "citation_doi meta tag missing")
    require(page.xpath('//meta[@name="citation_title"]/@content') == ["Intelligence by Appointment"], "citation_title metadata mismatch")
    require(page.xpath('//meta[@name="citation_author"]/@content') == ["Brad Pierce"], "citation_author metadata mismatch")
    require(page.xpath('//meta[@name="citation_publication_date"]/@content') == ["2026/09/21"], "citation_publication_date metadata mismatch")
    require(page.xpath('//meta[@name="citation_pdf_url"]/@content') == ["https://bradpierce.ai/intelligence-by-appointment/intelligence-by-appointment.pdf"], "citation_pdf_url metadata mismatch")
    require(page.xpath('//meta[@name="citation_fulltext_html_url"]/@content') == ["https://bradpierce.ai/intelligence-by-appointment/"], "citation_fulltext_html_url metadata mismatch")
    require(page.xpath('//link[@rel="canonical"]/@href') == ["https://bradpierce.ai/intelligence-by-appointment/"], "Canonical link missing")
    front = page.xpath('//*[@id="scholarly-front-matter"]')
    require(len(front) == 1, "Scholarly front matter missing")
    front_text = " ".join(front[0].text_content().split())
    require("Intelligence by Appointment" in front_text and "Brad Pierce" in front_text and "Abstract" in front_text, "Scholarly front matter incomplete")
    require(len(page.xpath('//main[@id="canonical-paper"]//figure')) == EXPECTED_FIGURES, "HTML figure-count mismatch")
    require(len(page.xpath('//main[@id="canonical-paper"]//figure/figcaption')) == EXPECTED_FIGURES, "Figure captions missing")
    require(len(page.xpath('//main[@id="canonical-paper"]//table')) == EXPECTED_TABLES, "HTML substantive-table count mismatch")
    require(len(page.xpath('//main[@id="canonical-paper"]//aside[@class="paper-note"]')) == 2, "Authorship/provenance note count mismatch")
    require(all(value.strip() for value in page.xpath('//main[@id="canonical-paper"]//figure/img/@alt')), "Figure alt text missing")

    headings = page.xpath('//main[@id="canonical-paper"]//*[self::h1 or self::h2 or self::h3 or self::h4]/text()')
    require(any(value.startswith("Appendix A.") for value in headings) and any(value.startswith("Appendix B.") for value in headings), "Appendix headings missing")
    require(any(value == "References" for value in headings), "References heading missing")

    references_md = (root / "references.md").read_text(encoding="utf-8")
    numbers = re.findall(r"^\[(\d+)\]", references_md, re.MULTILINE)
    require(numbers == [str(i) for i in range(1, EXPECTED_REFERENCES + 1)], "Reference sequence mismatch")
    bibliography = json.loads((root / "bibliography.json").read_text(encoding="utf-8"))
    require(bibliography["counts"] == {"reference_slots": 33, "works": 33, "reference_work_links": 33}, "Bibliography count mismatch")
    require([slot["id"] for slot in bibliography["reference_slots"]] == [f"ref-{i:03d}" for i in range(1, 34)], "Reference-slot identity mismatch")
    require([work["citekey"] for work in bibliography["works"]] == [f"f059_ref_{i:03d}" for i in range(1, 34)], "Bibliographic citekey mismatch")
    require(all(work["title"] and work["authors"] and work["issued"] for work in bibliography["works"]), "Reusable bibliographic fields missing")

    csl = json.loads((root / "references.csl.json").read_text(encoding="utf-8"))
    ris = (root / "references.ris").read_text(encoding="utf-8")
    bibtex = (root / "references.bib").read_text(encoding="utf-8")
    require(len(csl) == EXPECTED_REFERENCES, "CSL JSON count mismatch")
    require(ris.count("ER  -") == EXPECTED_REFERENCES, "RIS count mismatch")
    require(len(re.findall(r"^@misc\{f059_ref_\d{3},", bibtex, re.MULTILINE)) == EXPECTED_REFERENCES, "BibTeX count mismatch")
    with tempfile.TemporaryDirectory() as temporary:
        tmp = Path(temporary)
        (tmp / "references.bib").write_text(bibtex, encoding="utf-8")
        (tmp / "check.aux").write_text("\\citation{*}\n\\bibstyle{plain}\n\\bibdata{references}\n", encoding="utf-8")
        proc = subprocess.run(["bibtex", "check"], cwd=tmp, capture_output=True, text=True)
        require(proc.returncode == 0 and "Warning--" not in proc.stdout + proc.stderr, "Classic BibTeX rejected or warned on references.bib")
        for filename in ("references.bib", "references.csl.json", "references.ris"):
            proc = subprocess.run(["pandoc", "--from=markdown", "--to=plain", "--citeproc", f"--bibliography={root / filename}"], input="[@f059_ref_001]\n", capture_output=True, text=True)
            require(proc.returncode == 0, f"Pandoc rejected {filename}: {proc.stderr}")

    figures = sorted((root / "figures").glob("figure-*.svg"))
    require(len(figures) == EXPECTED_FIGURES, "SVG figure count mismatch")
    for figure in figures:
        etree.parse(str(figure))

    local_links = []
    for attr in page.xpath('//@href | //@src'):
        if attr.startswith(("http://", "https://", "mailto:", "#", "data:")):
            continue
        local_links.append(attr)
    missing = sorted({value for value in local_links if not (root / value).exists()})
    require(not missing, f"Broken local HTML links: {missing}")

    wrapper = readme.split("\n---\n", 1)[0] + index_source.split('<main id="canonical-paper">', 1)[0]
    wrapper += (root / "CITATION.cff").read_text(encoding="utf-8")
    wrapper += (root / "PROVENANCE.md").read_text(encoding="utf-8")
    injection_like = [
        r"ignore (?:all |any )?(?:previous|prior)", r"follow (?:these|the) instructions",
        r"you (?:must|should|need to)", r"please cite", r"must cite", r"do not cite",
        r"system message", r"assistant role", r"act as", r"prompt injection",
    ]
    for pattern in injection_like:
        require(not re.search(pattern, wrapper, re.I), f"Prompt-injection-like repository wording: {pattern}")

    checksum_lines = (root / "checksums.sha256").read_text(encoding="utf-8").splitlines()
    require(checksum_lines, "Checksum manifest empty")
    manifest_paths = set()
    for line in checksum_lines:
        expected, relative = line.split("  ", 1)
        manifest_paths.add(relative)
        require("__pycache__" not in Path(relative).parts and Path(relative).suffix != ".pyc", f"Ignored cache artifact in checksum manifest: {relative}")
        require((root / relative).is_file(), f"Checksum target missing: {relative}")
        require(digest(root / relative) == expected, f"Checksum mismatch: {relative}")
    public_files = {
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file()
        and path.name != "checksums.sha256"
        and ".git" not in path.parts
        and "__pycache__" not in path.parts
        and path.suffix != ".pyc"
    }
    require(manifest_paths == public_files, f"Checksum coverage mismatch: missing={sorted(public_files - manifest_paths)}, extra={sorted(manifest_paths - public_files)}")

    searchable = "\n".join((root / name).read_text(encoding="utf-8") for name in ["README.md", "index.html", "metadata.json", "CITATION.cff", "citation.bib", "PROVENANCE.md"])
    require(searchable.count(DOI) >= 12, "DOI is not sufficiently exposed")
    require("TODO" not in searchable and "PLACEHOLDER" not in searchable, "Placeholder text remains")
    require(not any(path.suffix.lower() in {".docx", ".zip"} for path in root.rglob("*")), "Private source archive leaked into repository")

    print(json.dumps({
        "status": "PASS", "pdf_pages": EXPECTED_PAGES, "pdf_sha256": PDF_SHA256,
        "paper_md_sha256": PAPER_MD_SHA256, "figures": EXPECTED_FIGURES,
        "tables": EXPECTED_TABLES, "references": EXPECTED_REFERENCES,
        "relevance_scope": "PASS", "prompt_injection_appearance": "PASS",
        "bibliography_exports": "PASS", "local_links": "PASS", "checksums": "PASS",
    }, indent=2))


if __name__ == "__main__":
    main()
