"""Best-effort PDF parsing with PyMuPDF.

PDFs vary widely. This parser preserves extracted page text exactly as PyMuPDF
returns it and marks figure/equation detections as heuristic metadata rather
than silently treating them as authoritative.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from loci.models.schemas import EquationCandidate, FigureCandidate, ParsedDocument


class PDFService:
    """Parse PDF text, image blocks, crops, captions, and obvious equations."""

    def __init__(self, crops_dir: str | Path) -> None:
        self.crops_dir = Path(crops_dir)
        self.crops_dir.mkdir(parents=True, exist_ok=True)

    def parse(self, path: str | Path) -> ParsedDocument:
        try:
            import fitz  # type: ignore
        except Exception as exc:  # pragma: no cover - environment-dependent
            raise RuntimeError("PDF ingestion requires PyMuPDF (`pip install PyMuPDF`).") from exc

        pdf_path = Path(path)
        doc = fitz.open(pdf_path)
        page_texts: list[str] = []
        page_offsets: list[tuple[int, int, int]] = []
        figures: list[FigureCandidate] = []
        equations: list[EquationCandidate] = []
        cursor = 0

        for page_index, page in enumerate(doc, start=1):
            page_text = page.get_text("text")
            header = f"\n\n[Page {page_index}]\n"
            start = cursor + len(header)
            page_texts.append(header + page_text)
            cursor += len(header) + len(page_text)
            page_offsets.append((page_index, start, cursor))

            equations.extend(self._detect_equations(page_text, page_index))
            figures.extend(self._extract_figures(page, pdf_path.stem, page_index))

        raw_text = "".join(page_texts).strip()
        title = doc.metadata.get("title") or pdf_path.stem
        return ParsedDocument(
            raw_text=raw_text,
            title=title,
            figures=figures,
            equations=equations,
            metadata={"page_count": doc.page_count, "page_offsets": page_offsets, "parser": "pymupdf"},
        )

    def _extract_figures(self, page: Any, stem: str, page_number: int) -> list[FigureCandidate]:
        figures: list[FigureCandidate] = []
        blocks = page.get_text("dict").get("blocks", [])
        image_index = 0
        for block in blocks:
            if block.get("type") != 1:
                continue
            bbox_tuple = tuple(float(v) for v in block.get("bbox", (0, 0, 0, 0)))
            rect = page.rect if not any(bbox_tuple) else bbox_tuple
            crop_path = self.crops_dir / f"{stem}_p{page_number}_{image_index}.png"
            try:
                pix = page.get_pixmap(clip=fitz_rect(page, rect), dpi=160)
                pix.save(crop_path)
            except Exception:
                pix = page.get_pixmap(dpi=120)
                pix.save(crop_path)
            figures.append(
                FigureCandidate(
                    page_number=page_number,
                    bbox=bbox_tuple,  # type: ignore[arg-type]
                    crop_path=str(crop_path),
                    caption=self._caption_near(page.get_text("text"), image_index),
                    confidence=0.55,
                )
            )
            image_index += 1
        return figures

    def _caption_near(self, page_text: str, image_index: int) -> str | None:
        captions = [line.strip() for line in page_text.splitlines() if re.match(r"^(Figure|Fig\.)\s+\d+", line.strip(), re.I)]
        return captions[min(image_index, len(captions) - 1)] if captions else None

    def _detect_equations(self, page_text: str, page_number: int) -> list[EquationCandidate]:
        candidates: list[EquationCandidate] = []
        for line in page_text.splitlines():
            stripped = line.strip()
            if not stripped or len(stripped) > 180:
                continue
            mathy = bool(re.search(r"[=∑∫√≤≥≈±]|\\frac|\\sum|\\int", stripped))
            has_symbols = len(re.findall(r"[+\-*/^=()]", stripped)) >= 2
            if mathy and has_symbols:
                candidates.append(
                    EquationCandidate(
                        page_number=page_number,
                        source_text=stripped,
                        mathjax=stripped.replace("≤", r"\le ").replace("≥", r"\ge ").replace("≈", r"\approx "),
                        confidence=0.45,
                    )
                )
        return candidates


def fitz_rect(page: Any, rect_or_tuple: Any) -> Any:
    """Build a fitz.Rect without importing fitz at module import time."""

    import fitz  # type: ignore

    if hasattr(rect_or_tuple, "x0"):
        return rect_or_tuple
    return fitz.Rect(*rect_or_tuple)
